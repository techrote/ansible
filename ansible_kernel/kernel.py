"""Admission, durable lifecycle, and evidence. One active job per state root."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
import uuid

from . import CONTRACT, VERSION
from . import provider
from .contract import (Refusal, canonical, decode, digest, make_request, outcome,
                       rejection, request, slot)
from .slot_transport import TransportError, validate_snapshot
from .state import (StateError, Store, TERMINAL, append, journal, plain, read_bytes,
                    write_once)


ROOT = Path(__file__).resolve().parent.parent


def fingerprint() -> str:
    hasher = hashlib.sha256()
    paths = sorted((ROOT / "ansible_kernel").glob("*.py")) + sorted((ROOT / "schemas").glob("*.json"))
    paths += [ROOT / "run_kernel.py", ROOT / "run_slot_transport.py"]
    for path in paths:
        hasher.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


class Kernel:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def _ledger(self) -> list[dict]:
        rows = journal(self.store.ledger)
        observed = {}
        jobs, requests, once = set(), set(), set()

        def observe(value: dict) -> None:
            previous = observed.get(value["slot"])
            if previous is not None:
                self._compare_generation(previous, value)
            observed[value["slot"]] = value

        try:
            for row in rows:
                kind = row.get("type")
                if kind == "reserved":
                    if set(row) != {"type", "job_id", "request_key", "request_digest", "once_key"}:
                        raise StateError("INVALID_LEDGER_EVENT")
                    self.store.job(row["job_id"])
                    for key in ("request_key", "request_digest"):
                        if type(row[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                            raise StateError("INVALID_LEDGER_EVENT")
                    if row["once_key"] is not None and (type(row["once_key"]) is not str
                            or not re.fullmatch(r"[1-4]:[1-9][0-9]{0,9}", row["once_key"])):
                        raise StateError("INVALID_LEDGER_EVENT")
                    if (row["job_id"] in jobs or row["request_key"] in requests
                            or row["once_key"] is not None and row["once_key"] in once):
                        raise StateError("DUPLICATE_RESERVATION")
                    jobs.add(row["job_id"])
                    requests.add(row["request_key"])
                    if row["once_key"] is not None:
                        once.add(row["once_key"])
                elif kind == "slot_seen":
                    if set(row) != {"type", "slot"}:
                        raise StateError("INVALID_LEDGER_EVENT")
                    observe(slot(canonical(row["slot"])))
                elif kind in ("slots_refreshed", "slots_remote_refreshed"):
                    keys = {"type", "slots", "provenance"} if kind == "slots_remote_refreshed" else {"type", "slots"}
                    if set(row) != keys or type(row["slots"]) is not list or len(row["slots"]) != 4:
                        raise StateError("INVALID_LEDGER_EVENT")
                    if kind == "slots_remote_refreshed":
                        validate_snapshot({"slots": row["slots"], "provenance": row["provenance"]})
                    for number, value in enumerate(row["slots"], 1):
                        observe(slot(canonical(value), number))
                else:
                    raise StateError("UNKNOWN_LEDGER_EVENT")
        except (Refusal, TransportError, TypeError, KeyError) as exc:
            raise StateError("INVALID_LEDGER_EVENT") from exc
        return rows

    def _recover(self) -> list[str]:
        recovered = []
        for status in self.store.statuses():
            job_id = status["job_id"]
            if status["state"] == "unreadable":
                raise StateError("RECOVERY_REQUIRES_JOURNAL_REPAIR")
            if status["state"] in TERMINAL:
                continue
            rows = self.store.events(job_id)
            if not rows:
                self.store.transition(job_id, "created")
            admitted = any(row["state"] == "admitted" for row in rows)
            value = {"contract_version": CONTRACT, "implementation_version": VERSION,
                     "job_id": job_id, "admission": "admitted" if admitted else "rejected_policy",
                     "infrastructure": {"state": "unknown", "exit_code": None, "controller_completed": False},
                     "transport": "not_applicable", "worker_outcome": "unknown",
                     "evidence": "partial", "reason": "OWNER_LOST_REQUIRES_REVIEW"}
            with self.store.control_lock(job_id):
                self.store.transition(job_id, "failed", result=value)
            recovered.append(job_id)
        return recovered

    def recover(self) -> list[str]:
        with self.store.lock():
            self._ledger()  # Do not recover across a damaged reservation ledger.
            return self._recover()

    def _snapshot(self, rows: list[dict]) -> list[dict]:
        # Recorded observations outrank checkout defaults. In particular a
        # slot_seen-only v0.1.1 history must survive a trusted source update.
        values = {n: slot(read_bytes(ROOT / "slots" / f"slot{n}.json"), n)
                  for n in range(1, 5)}
        for row in rows:
            if row["type"] in ("slots_refreshed", "slots_remote_refreshed"):
                values = {value["slot"]: value for value in row["slots"]}
            elif row["type"] == "slot_seen":
                values[row["slot"]["slot"]] = row["slot"]
        return [slot(canonical(values[n]), n) for n in range(1, 5)]

    def _slots(self) -> list[dict]:
        return self._snapshot(self._ledger())

    def slots(self) -> list[dict]:
        return self._slots()

    @staticmethod
    def _compare_generation(previous: dict, value: dict) -> None:
        if value["generation"] < previous["generation"]:
            raise Refusal("GENERATION_ROLLBACK", "rejected_policy")
        if value["generation"] == previous["generation"] and digest(value) != digest(previous):
            raise Refusal("GENERATION_CONTENT_CHANGED", "rejected_policy")

    def _generation(self, value: dict) -> None:
        self._compare_generation(self._slots()[value["slot"] - 1], value)

    def refresh(self, directory: Path) -> list[dict]:
        # This is an operator API, not a request field. Reads exactly four JSON files.
        directory = Path(directory).absolute()
        plain(directory)
        values = [slot(read_bytes(directory / f"slot{n}.json"), n) for n in range(1, 5)]
        with self.store.lock():
            rows = self._ledger()
            current = self._snapshot(rows)
            for previous, value in zip(current, values):
                self._compare_generation(previous, value)
            # Persist the first full snapshot, even when it matches bootstrap.
            # Repeating an already-recorded snapshot is a read-only success.
            if (values != current
                    or not any(row["type"] in ("slots_refreshed", "slots_remote_refreshed") for row in rows)):
                append(self.store.ledger, {"type": "slots_refreshed", "slots": values})
        return values

    @staticmethod
    def _slot_source(rows: list[dict]) -> dict | None:
        seen = {}
        for row in reversed(rows):
            if row["type"] == "slot_seen":
                seen.setdefault(row["slot"]["slot"], row["slot"])
            if row["type"] == "slots_remote_refreshed":
                if any(digest(v) != digest(row["slots"][n - 1]) for n, v in seen.items()):
                    return None
                return row["provenance"]
            if row["type"] == "slots_refreshed":
                return None
        return None

    def slot_source(self) -> dict | None:
        return self._slot_source(self._ledger())

    def refresh_remote(self, snapshot: dict) -> dict:
        snapshot = validate_snapshot(snapshot)
        values, proof = snapshot["slots"], snapshot["provenance"]
        with self.store.lock():
            rows = self._ledger()
            current = self._snapshot(rows)
            for previous, value in zip(current, values):
                self._compare_generation(previous, value)
            changed = values != current or proof != self._slot_source(rows)
            if changed:
                append(self.store.ledger, {"type": "slots_remote_refreshed", **snapshot})
        return {"contract_version": "ansible.remote-refresh.v1", "changed": changed,
                "slots": values, "provenance": proof}

    def execute(self, raw: bytes) -> dict:
        with self.store.lock():
            self._ledger()
            self._recover()
            return self._execute(raw)

    def run_slot(self, number: int) -> dict:
        if type(number) is not int or not 1 <= number <= 4:
            raise Refusal("INVALID_SLOT")
        with self.store.lock():
            self._ledger()
            self._recover()
            value = None
            try:
                value = self._slots()[number - 1]
                self._generation(value)
                if value["state"] != "armed":
                    raise Refusal("SLOT_IDLE", "rejected_policy")
                wire = make_request("slot-" + str(number) + "-" + uuid.uuid4().hex)
                wire["runner_id"] = value["runner_type"]
                wire["timeout_seconds"] = value["timeout_seconds"]
                return self._execute(canonical(wire), value)
            except Refusal as exc:
                return self._rejected(exc, b"slot", slot_value=value)

    @staticmethod
    def _slot_context(value: dict | None) -> dict | None:
        return ({"slot": value["slot"], "generation": value["generation"]}
                if value is not None else None)

    def _rejected(self, exc: Refusal, raw: bytes, job_id: str | None = None,
                  slot_value: dict | None = None) -> dict:
        if job_id is None:
            job_id = self.store.new_job({"input_sha256": hashlib.sha256(raw).hexdigest(),
                                         "contract_version": CONTRACT, "implementation_version": VERSION,
                                         "slot_context": self._slot_context(slot_value)})
        result = rejection(job_id, exc)
        with self.store.control_lock(job_id):
            write_once(self.store.job(job_id) / "result.json", canonical(result) + b"\n")
            self.store.transition(job_id, "rejected", result=result)
        return result

    def _execute(self, raw: bytes, slot_value: dict | None = None) -> dict:
        source = fingerprint()
        job_id = self.store.new_job({"input_sha256": hashlib.sha256(raw).hexdigest(),
                                     "contract_version": CONTRACT, "implementation_version": VERSION,
                                     "source_fingerprint": source,
                                     "slot_context": self._slot_context(slot_value)})
        path = self.store.job(job_id)
        try:
            value, runner = request(raw)
            self.store.transition(job_id, "validated")
            rows = self._ledger()
            request_key = digest(value["request_id"])
            if any(row["type"] == "reserved" and row["request_key"] == request_key for row in rows):
                raise Refusal("REQUEST_ALREADY_RESERVED", "rejected_policy")
            once_key = None
            if slot_value is not None:
                self._generation(slot_value)
                if slot_value["run_policy"] == "once":
                    once_key = f'{slot_value["slot"]}:{slot_value["generation"]}'
                    if any(row["type"] == "reserved" and row.get("once_key") == once_key for row in rows):
                        raise Refusal("GENERATION_ALREADY_RESERVED", "rejected_policy")
                append(self.store.ledger, {"type": "slot_seen", "slot": slot_value})
            # Durable claim BEFORE launch: a crash consumes an at-most-once attempt.
            append(self.store.ledger, {"type": "reserved", "job_id": job_id,
                                      "request_key": request_key, "request_digest": digest(value),
                                      "once_key": once_key})
            self.store.transition(job_id, "admitted")
        except Refusal as exc:
            return self._rejected(exc, raw, job_id)
        self.store.transition(job_id, "starting")
        try:
            normalized, infra, stop, metadata = provider.run(
                job_id, value, self.store, lambda: self.store.transition(job_id, "running"))
        except KeyboardInterrupt:
            normalized, stop, metadata = None, "cancelled", {"error": "OPERATOR_INTERRUPT"}
            infra = {"state": "terminated", "exit_code": None, "controller_completed": True}
        except Exception:
            # Provider finally owns cleanup. Never reinterpret a controller exception as success.
            normalized, stop, metadata = None, None, {"error": "CONTROLLER_EXCEPTION"}
            infra = {"state": "controller_failed", "exit_code": None, "controller_completed": False}
        write_once(path / "provider.json", canonical(metadata) + b"\n")
        evidence = "partial"
        if normalized is not None:
            write_once(path / "worker.json", normalized + b"\n")
            manifest = {name: hashlib.sha256(read_bytes(path / name)).hexdigest() for name in runner.evidence}
            write_once(path / "manifest.json", canonical(manifest) + b"\n")
            evidence = self.store.verify_evidence(job_id)
        if fingerprint() != source:
            infra = {**infra, "state": "environment_failed"}
        with self.store.control_lock(job_id):
            # Linearize control receipt against terminal publication; containment wins.
            control = self.store.stop_reason(job_id)
            if control == "contained" or stop is None:
                stop = control or stop
            result = outcome(job_id, normalized, infra, evidence, runner.predicate, stop)
            if stop is not None and infra["state"] == "controller_failed":
                result = {**result, "worker_outcome": "unknown", "reason": "TERMINATION_UNCONFIRMED"}
            terminal = {"success": "completed", "cancelled": "cancelled", "contained": "contained",
                        "timeout": "timeout"}.get(result["worker_outcome"], "failed")
            write_once(path / "result.json", canonical(result) + b"\n")
            self.store.transition(job_id, terminal, result=result)
        return result
