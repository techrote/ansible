"""Strict wire data, immutable registry, and runner-owned semantic predicates.

No imports, callable paths, commands, or policies are loaded from request data.
The schema evaluator deliberately implements only the subset used in this repo.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

from . import CONTRACT, WORKER_CONTRACT, VERSION

MAX_BYTES = 65536
SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"


class Refusal(ValueError):
    def __init__(self, code: str, admission: str = "rejected_schema"):
        self.code, self.admission = code, admission
        super().__init__(code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("ascii")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(raw: bytes) -> Any:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise Refusal("INPUT_TOO_LARGE")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refusal("DUPLICATE_KEY")
            result[key] = value
        return result

    def constant(_):
        raise Refusal("NONFINITE_NUMBER")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=constant, parse_float=constant)
        count = 0

        def visit(value, depth=0):
            nonlocal count
            count += 1
            if count > 4096 or depth > 20:
                raise Refusal("INPUT_COMPLEXITY")
            if isinstance(value, str):
                value.encode("utf-8", errors="strict")
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    visit(child, depth + 1)
        visit(result)
        return result
    except Refusal:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError) as exc:
        raise Refusal("INVALID_JSON") from exc


def validate(value: Any, schema: dict) -> None:
    supported = {"$schema", "$id", "title", "description", "type", "const", "enum",
                 "required", "properties", "additionalProperties", "minimum", "maximum",
                 "minLength", "maxLength", "pattern", "items", "minItems", "maxItems",
                 "uniqueItems"}
    if set(schema) - supported:
        raise RuntimeError("Unsupported trusted schema keyword")
    types = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "null": type(None)}
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    if kind is not None and not any(type(value) is types[k] for k in kinds):
        raise Refusal("INVALID_TYPE")
    if "const" in schema and (type(value) is not type(schema["const"])
                              or value != schema["const"]):
        raise Refusal("INVALID_CONSTANT")
    if "enum" in schema and not any(type(value) is type(v) and value == v
                                    for v in schema["enum"]):
        raise Refusal("INVALID_ENUM")
    if type(value) is dict:
        properties = schema.get("properties", {})
        if not set(schema.get("required", ())) <= value.keys():
            raise Refusal("MISSING_FIELD")
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise Refusal("UNKNOWN_FIELD")
        for key, child in value.items():
            if key in properties:
                validate(child, properties[key])
    elif type(value) is list:
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 4096):
            raise Refusal("ARRAY_LENGTH")
        if schema.get("uniqueItems") and len({canonical(x) for x in value}) != len(value):
            raise Refusal("DUPLICATE_ITEM")
        for child in value:
            if "items" in schema:
                validate(child, schema["items"])
    elif type(value) is str:
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", MAX_BYTES):
            raise Refusal("STRING_LENGTH")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise Refusal("STRING_PATTERN")
    elif type(value) is int:
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            raise Refusal("NUMBER_RANGE")


def schema(name: str) -> dict:
    # name comes from trusted code only; never from a wire message.
    return decode((SCHEMAS / name).read_bytes())


def check(value: Any, name: str) -> None:
    validate(value, schema(name))


@dataclass(frozen=True)
class Predicate:
    output: str | None = None
    implementation: bool = False
    min_tool_calls: int = 0

    def accepts(self, normalized: dict) -> bool:
        output = normalized["final_output"]
        return (isinstance(output, str) and bool(output.strip())
                and (self.output is None or output == self.output)
                and (not self.implementation or normalized["implementation_activity"])
                and normalized["tool_calls"] >= self.min_tool_calls)


@dataclass(frozen=True)
class Runner:
    runner_id: str
    enabled: bool
    predicate: Predicate
    runner_contract: str = "ansible.runner.noop.v1"
    provider_id: str = "trusted_local_v1"
    max_timeout: int = 30
    max_memory_mb: int = 256
    max_cpu_seconds: int = 2
    evidence: tuple[str, ...] = ("worker.json", "provider.json")


REGISTRY = MappingProxyType({
    "noop_v1": Runner("noop_v1", True, Predicate(output="trusted noop complete")),
    "omp_blind_review_v1": Runner("omp_blind_review_v1", False, Predicate(),
                                 runner_contract="unqualified"),
})


def request(raw: bytes) -> tuple[dict, Runner]:
    value = decode(raw)
    if isinstance(value, dict) and value.get("contract_version") != CONTRACT:
        raise Refusal("INCOMPATIBLE_CONTRACT", "rejected_policy")
    check(value, "execution-v1.schema.json")
    runner = REGISTRY.get(value["runner_id"])
    if runner is None:
        raise Refusal("UNKNOWN_RUNNER", "rejected_runner")
    if not runner.enabled:
        raise Refusal("RUNNER_NOT_QUALIFIED", "rejected_runner")
    if value["capabilities"]:
        raise Refusal("CAPABILITY_NOT_GRANTED", "rejected_capability")
    if value["provider_id"] != runner.provider_id:
        raise Refusal("PROVIDER_NOT_QUALIFIED", "rejected_policy")
    limits = value["resources"]
    if (value["timeout_seconds"] > runner.max_timeout
            or limits["memory_mb"] > runner.max_memory_mb
            or limits["cpu_seconds"] > runner.max_cpu_seconds):
        raise Refusal("RESOURCE_ENVELOPE_EXCEEDED", "rejected_policy")
    check(value["parameters"], "noop-v1.schema.json")
    return value, runner


def make_request(request_id: str, duration_ms: int = 0) -> dict:
    return {"contract_version": CONTRACT, "request_id": request_id,
            "runner_id": "noop_v1", "provider_id": "trusted_local_v1",
            "parameters": {"duration_ms": duration_ms}, "capabilities": [],
            "timeout_seconds": 30, "resources": {"memory_mb": 256, "cpu_seconds": 2}}


def safe_ref(value: str) -> None:
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,159}", value)
            or any(x in value for x in ("..", "//", "@{"))
            or any(x.startswith(".") or x.endswith((".", ".lock")) for x in value.split("/"))
            or value.endswith("/")):
        raise Refusal("UNSAFE_REF")


def safe_relative(value: str) -> None:
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
    if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,259}", value)
            or any(x in ("", ".", "..") or x.endswith((".", " "))
                   or x.split(".")[0].upper() in reserved for x in value.split("/"))):
        raise Refusal("UNSAFE_PATH")


def slot(raw: bytes, expected_slot: int | None = None) -> dict:
    value = decode(raw)
    check(value, "slot-v1.schema.json")
    if expected_slot is not None and value["slot"] != expected_slot:
        raise Refusal("SLOT_MISMATCH")
    if value["generation"] > 2147483647:
        raise Refusal("GENERATION_RANGE")
    for key in ("task_id", "label", "model"):
        if key in value and any(ord(c) < 32 or ord(c) == 127 for c in value[key]):
            raise Refusal("CONTROL_CHARACTER")
    if "target" in value:
        safe_ref(value["target"]["remote_branch"])
    if "reference" in value:
        safe_ref(value["reference"]["ref"])
        safe_relative(value["reference"]["path"])
    for path in value.get("preflight", {}).get("pytest_paths", []):
        safe_relative(path)
        if not path.startswith("tests/") or not path.endswith(".py"):
            raise Refusal("UNSAFE_TEST_PATH")
    if value["state"] == "armed":
        if not {"runner_type", "run_policy", "timeout_seconds"} <= value.keys():
            raise Refusal("ARMED_FIELDS_REQUIRED")
        if value["runner_type"] == "noop_v1" and value.keys() & {"model", "target", "reference", "preflight"}:
            raise Refusal("NOOP_UNUSED_AUTHORITY")
    return value


def outcome(job_id: str, normalized: bytes | None, infra: dict,
            evidence: str, predicate: Predicate, stop: str | None = None) -> dict:
    """Infrastructure/stop/evidence are host observations, NOT worker assertions."""
    worker, transport, reason = "unknown", "not_applicable", "NO_WORKER_RESULT"
    parsed = None
    if normalized is not None:
        try:
            parsed = decode(normalized)
            if isinstance(parsed, dict) and parsed.get("contract_version") != WORKER_CONTRACT:
                raise Refusal("INCOMPATIBLE_WORKER_CONTRACT")
            check(parsed, "worker-v1.schema.json")
            if parsed["job_id"] != job_id:
                raise Refusal("WRONG_JOB_RESULT")
            transport = parsed["transport"]
        except Refusal as exc:
            parsed, worker, transport, reason = None, "invalid_result", "protocol_failed", exc.code
    if parsed is not None:
        worker, reason = parsed["outcome"], "WORKER_REPORTED"
        if parsed["retry_exhausted"]:
            transport = "retry_exhausted"
        if parsed["error_class"] == "provider" or worker == "provider_error":
            worker, reason = "provider_error", "PROVIDER_ERROR"
        elif parsed["retry_exhausted"] or transport == "retry_exhausted":
            worker, transport, reason = "provider_error", "retry_exhausted", "RETRY_EXHAUSTED"
        elif parsed["error_class"] == "worker":
            worker, reason = "worker_error", "WORKER_ERROR"
        elif transport not in ("ready", "not_applicable"):
            worker, reason = "invalid_result", "TRANSPORT_FAILURE"
        elif worker == "success" and not predicate.accepts(parsed):
            worker = "no_result" if not parsed["final_output"] or not parsed["final_output"].strip() else "invalid_result"
            reason = "SUCCESS_PREDICATE_UNSATISFIED"
    elif normalized is None:
        worker = "no_result"
    if stop in ("cancelled", "timeout", "contained"):
        worker, reason = stop, "HOST_" + stop.upper()
    elif infra["state"] != "completed" or infra["exit_code"] != 0 or not infra["controller_completed"]:
        # Keep a known provider/worker error rather than erasing that evidence.
        if worker == "success" or normalized is None:
            worker = "unknown"
        reason = "INFRASTRUCTURE_FAILURE"
    elif evidence != "complete" and worker == "success":
        worker, reason = "invalid_result", "EVIDENCE_INCOMPLETE"
    result = {"contract_version": CONTRACT, "implementation_version": VERSION,
              "job_id": job_id, "admission": "admitted", "infrastructure": infra,
              "transport": transport, "worker_outcome": worker,
              "evidence": evidence, "reason": reason}
    check(result, "result-v1.schema.json")
    return result


def rejection(job_id: str, exc: Refusal) -> dict:
    value = {"contract_version": CONTRACT, "implementation_version": VERSION,
             "job_id": job_id, "admission": exc.admission,
             "infrastructure": {"state": "not_started", "exit_code": None, "controller_completed": True},
             "transport": "not_applicable", "worker_outcome": "unknown",
             "evidence": "complete", "reason": exc.code}
    check(value, "result-v1.schema.json")
    return value
