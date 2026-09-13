"""Bounded read-only observations for local clients, not orchestration authority."""
from __future__ import annotations

import time

from . import CONTRACT, VERSION
from .contract import Refusal, check, decode
from .state import StateError, Store, TERMINAL, read_bytes

STATUS_CONTRACT = "ansible.job-status.v1"
EVENTS_CONTRACT = "ansible.events.v1"
MAX_PAGE_SIZE = 128
MAX_CURSOR = 2147483647


def _rows(store: Store, job_id: str) -> list[dict]:
    if not store.job(job_id).is_dir():
        raise StateError("UNKNOWN_JOB")
    return store.events(job_id)


def _binding(store: Store, job_id: str) -> dict | None:
    try:
        metadata = decode(read_bytes(store.job(job_id) / "metadata.json"))
        if type(metadata) is not dict:
            raise StateError("INVALID_JOB_METADATA")
        binding = metadata.get("slot_context")
        if binding is not None:
            if (type(binding) is not dict or set(binding) != {"slot", "generation"}
                    or type(binding["slot"]) is not int or not 1 <= binding["slot"] <= 4
                    or type(binding["generation"]) is not int
                    or not 1 <= binding["generation"] <= MAX_CURSOR):
                raise StateError("INVALID_SLOT_CONTEXT")
        return binding
    except Refusal as exc:
        raise StateError("INVALID_JOB_METADATA") from exc


def inspect_job(store: Store, job_id: str, *, now_ns: int | None = None) -> dict:
    rows = _rows(store, job_id)
    state = rows[-1]["state"] if rows else "unknown"
    terminal = state in TERMINAL
    start = rows[0]["time_ns"] if rows else None
    latest = rows[-1]["time_ns"] if rows else None
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now <= 0:
        raise StateError("INVALID_QUERY_CLOCK")
    end = latest if terminal else now
    control = store.stop_reason(job_id)
    value = {
        "contract_version": STATUS_CONTRACT, "execution_contract": CONTRACT,
        "implementation_version": VERSION, "job_id": job_id,
        "state": state, "terminal": terminal, "event_count": len(rows),
        "started_time_ns": start, "last_event_time_ns": latest,
        "elapsed_ms": max(0, (end - start) // 1_000_000) if start is not None else 0,
        "slot_context": _binding(store, job_id),
        "control_requested": {"cancelled": "cancel", "contained": "contain"}.get(control),
        "verified_result": store._result_from_events(job_id, rows),
    }
    check(value, "job-status-v1.schema.json")
    return value


def events_page(store: Store, job_id: str, *, after: int = 0, limit: int = 100) -> dict:
    if type(after) is not int or not 0 <= after <= MAX_CURSOR:
        raise StateError("INVALID_EVENT_CURSOR")
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise StateError("INVALID_EVENT_PAGE_SIZE")
    rows = _rows(store, job_id)
    if after > len(rows):
        raise StateError("EVENT_CURSOR_AHEAD")
    end = min(len(rows), after + limit)
    # Never export stale raw terminal success: only the separately revalidated
    # result is suitable for a caller's success decision.
    events = [{"sequence": index + 1, "state": rows[index]["state"],
               "time_ns": rows[index]["time_ns"]} for index in range(after, end)]
    value = {
        "contract_version": EVENTS_CONTRACT, "execution_contract": CONTRACT,
        "job_id": job_id, "after": after, "next_cursor": end,
        "total_events": len(rows), "has_more": end < len(rows),
        "terminal": bool(rows and rows[-1]["state"] in TERMINAL),
        "events": events, "verified_result": store._result_from_events(job_id, rows),
    }
    check(value, "events-v1.schema.json")
    return value
