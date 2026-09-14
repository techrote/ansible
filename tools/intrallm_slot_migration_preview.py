"""Offline, credential-free preview for the legacy intrallm slot migration.

This operator tool intentionally does not contact GitHub or modify any repository.
It generates four idle current-schema assignments, validates them with the production
slot contract and fixed-origin transport verifier, and simulates publication against
a temporary kernel state while preserving the shipped generation-1 once claim.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ansible_kernel.contract import canonical, digest, slot
from ansible_kernel.kernel import Kernel
from ansible_kernel.slot_transport import PREFIX, REF_PATH, SOURCE_REF, collect_snapshot, git_oid
from ansible_kernel.state import Store, journal

PREVIEW_CONTRACT = "ansible.intrallm-slot-migration-preview.v1"
RECORDED_REPOSITORY_GENERATION_FLOOR = 1
SYNTHETIC_COMMIT_SHA = "f" * 40
OBSERVED_REMOTE_COMMIT = "67a55d339863f603d333c7a327cd2eb7cb1f54b5"
OBSERVED_REMOTE_BLOBS = (
    "5fc85cdebc456290634e9bf71a0ed42210d55499",
    "f40be08f6f472988ceb37d4572d74551147950d1",
    "c9e60abf713fec274529337d8744a270060e86ed",
    "5e809dd3390804153be7d424d2282b8567f2951a",
)


def candidate_slots(generation: int) -> list[dict]:
    if type(generation) is not int or generation <= RECORDED_REPOSITORY_GENERATION_FLOOR:
        raise ValueError("GENERATION_NOT_ABOVE_RECORDED_FLOOR")
    values = []
    for number in range(1, 5):
        value = {
            "schema_version": 1,
            "slot": number,
            "generation": generation,
            "state": "idle",
            "task_id": f"slot-{number}-intrallm-migration-g{generation}",
            "label": "Idle",
        }
        values.append(slot(canonical(value), number))
    return values


def _tree_response(entries: list[dict]) -> tuple[str, bytes]:
    ordered = sorted(entries, key=lambda entry: (
        entry["path"] + ("/" if entry["mode"] == "040000" else "")
    ).encode("utf-8"))
    raw = b"".join(
        entry["mode"].lstrip("0").encode("ascii") + b" "
        + entry["path"].encode("utf-8") + b"\0" + bytes.fromhex(entry["sha"])
        for entry in ordered
    )
    sha = git_oid("tree", raw)
    return sha, canonical({"sha": sha, "tree": entries, "truncated": False})


def synthetic_transport_snapshot(values: list[dict]) -> tuple[dict, int]:
    raw_slots = [canonical(value) + b"\n" for value in values]
    entries = [
        {
            "path": f"slot{number}.json",
            "mode": "100644",
            "type": "blob",
            "sha": git_oid("blob", raw),
            "size": len(raw),
        }
        for number, raw in enumerate(raw_slots, 1)
    ]
    slots_sha, slots_tree = _tree_response(entries)
    root_sha, root_tree = _tree_response([
        {"path": "slots", "mode": "040000", "type": "tree", "sha": slots_sha}
    ])
    responses = {
        REF_PATH: canonical({
            "ref": SOURCE_REF,
            "object": {"type": "commit", "sha": SYNTHETIC_COMMIT_SHA},
        }),
        PREFIX + "commits/" + SYNTHETIC_COMMIT_SHA: canonical({
            "sha": SYNTHETIC_COMMIT_SHA,
            "tree": {"sha": root_sha},
        }),
        PREFIX + "trees/" + root_sha: root_tree,
        PREFIX + "trees/" + slots_sha: slots_tree,
    }
    responses.update({
        PREFIX + "blobs/" + entry["sha"]: raw
        for entry, raw in zip(entries, raw_slots)
    })
    calls: list[tuple[str, bool]] = []

    def read(path: str, *, raw: bool = False) -> bytes:
        calls.append((path, raw))
        return responses[path]

    return collect_snapshot(read), len(calls)


def simulate_publication(snapshot: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="ansible-slot-migration-preview-") as directory:
        store = Store(Path(directory) / "state")
        kernel = Kernel(store)
        baseline = kernel.slots()
        baseline_once = kernel.run_slot(1)
        rows_before = journal(store.ledger)
        reserved_before = [
            row["once_key"] for row in rows_before
            if row.get("type") == "reserved" and row.get("once_key") is not None
        ]
        first = kernel.refresh_remote(copy.deepcopy(snapshot))
        ledger_after_first = store.ledger.read_bytes()
        second = kernel.refresh_remote(copy.deepcopy(snapshot))
        rows_after = journal(store.ledger)
        reserved_after = [
            row["once_key"] for row in rows_after
            if row.get("type") == "reserved" and row.get("once_key") is not None
        ]
        current = kernel.slots()
        return {
            "baseline_generations": [value["generation"] for value in baseline],
            "baseline_once_completed": baseline_once.get("worker_outcome") == "success",
            "generation_1_once_reserved_before": "1:1" in reserved_before,
            "first_refresh_changed": first["changed"],
            "repeat_refresh_changed": second["changed"],
            "repeat_refresh_ledger_unchanged": store.ledger.read_bytes() == ledger_after_first,
            "generation_1_once_preserved": "1:1" in reserved_after,
            "current_generations": [value["generation"] for value in current],
            "all_current_slots_idle": all(value["state"] == "idle" for value in current),
        }


def build_report(generation: int = 2) -> dict:
    values = candidate_slots(generation)
    snapshot, reads = synthetic_transport_snapshot(values)
    simulation = simulate_publication(snapshot)
    raw_files = [canonical(value) + b"\n" for value in values]
    return {
        "contract_version": PREVIEW_CONTRACT,
        "generation": generation,
        "recorded_repository_generation_floor": RECORDED_REPOSITORY_GENERATION_FLOOR,
        "connector_read_only_observation": {
            "repository": "techrote/intrallm",
            "ref": SOURCE_REF,
            "commit_sha": OBSERVED_REMOTE_COMMIT,
            "blob_shas": list(OBSERVED_REMOTE_BLOBS),
            "legacy_generations": [1, 1, 1, 1],
            "legacy_schema_rejected_without_translation": True,
            "observation_requires_recheck_before_publication": True,
        },
        "deployment_generation_check_required": True,
        "producer_write_performed": False,
        "credential_used": False,
        "authenticated_remote_refresh_performed": False,
        "transport_preview": {
            "attestation": "synthetic_in_memory_git_graph",
            "fixed_reads": reads,
            "provenance_contract": snapshot["provenance"]["contract_version"],
            "slots_digest": snapshot["provenance"]["slots_digest"],
            "root_tree_sha": snapshot["provenance"]["root_tree_sha"],
            "slots_tree_sha": snapshot["provenance"]["slots_tree_sha"],
        },
        "files": [
            {
                "path": f"slots/slot{number}.json",
                "blob_sha": git_oid("blob", raw),
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "value_sha256": digest(value),
                "bytes": len(raw),
                "value": value,
            }
            for number, (value, raw) in enumerate(zip(values, raw_files), 1)
        ],
        "publication_simulation": simulation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview the data-only intrallm slot migration offline")
    parser.add_argument("--generation", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.generation)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
