"""Fixed-origin, data-only GitHub slot transport; never a worker capability.

The authenticated GitHub API attests ref -> commit -> root tree. Tree and blob
Git object IDs are independently recomputed; SHA-256 also identifies slot bytes.
No URL, command, executable, proxy, or credential helper is accepted from data.
"""
from __future__ import annotations

import hashlib
import http.client
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import threading
import time
from typing import Callable

from .contract import MAX_BYTES, Refusal, canonical, check, decode, digest, slot
from .provider import Capture, WindowsJob, clean_environment, terminate

HOST = "api.github.com"
REPOSITORY = "techrote/intrallm"
SOURCE_REF = "refs/heads/control/launcher-slots"
SOURCE_ID = "intrallm_slots_v1"
CONTRACT = "ansible.slot-source.v1"
PREFIX = "/repos/" + REPOSITORY + "/git/"
REF_PATH = PREFIX + "ref/" + SOURCE_REF.removeprefix("refs/")
API_VERSION = "2026-03-10"
MAX_REQUESTS = 8
MAX_TREE_ENTRIES = 128
MAX_SNAPSHOT_BYTES = 60000
NETWORK_SECONDS = 25
HELPER_SECONDS = 30
ERRORS = frozenset({
    "REMOTE_SLOTS_DISABLED", "TRANSPORT_CREDENTIAL_REQUIRED", "TRANSPORT_CREDENTIAL_INVALID",
    "TRANSPORT_PATH_REFUSED", "TRANSPORT_REQUEST_LIMIT", "TRANSPORT_RESPONSE_LIMIT",
    "TRANSPORT_TIMEOUT", "TRANSPORT_REDIRECT_REFUSED", "TRANSPORT_AUTH_FAILED",
    "TRANSPORT_NOT_FOUND", "TRANSPORT_RATE_LIMITED", "TRANSPORT_HTTP_FAILED",
    "TRANSPORT_IO_FAILED", "TRANSPORT_PROTOCOL_FAILED", "TRANSPORT_REF_MISMATCH",
    "TRANSPORT_COMMIT_MISMATCH", "TRANSPORT_TREE_INVALID", "TRANSPORT_TREE_HASH_MISMATCH",
    "TRANSPORT_PATH_MISSING", "TRANSPORT_FILE_MODE_REFUSED", "TRANSPORT_BLOB_MISMATCH",
    "REMOTE_SLOT_SCHEMA_INVALID", "TRANSPORT_SNAPSHOT_INVALID", "TRANSPORT_HELPER_FAILED",
    "TRANSPORT_OUTPUT_LIMIT", "TRANSPORT_PLATFORM_UNQUALIFIED", "TRANSPORT_INTERRUPTED",
})


class TransportError(ValueError):
    def __init__(self, code: str):
        self.code = code if code in ERRORS else "TRANSPORT_PROTOCOL_FAILED"
        super().__init__(self.code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise TransportError(code)


def oid(value: object) -> str:
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
            "TRANSPORT_PROTOCOL_FAILED")
    return value


def git_oid(kind: str, raw: bytes) -> str:
    # Git SHA-1 object identity, not a substitute for authentication or SHA-256.
    return hashlib.sha1(kind.encode("ascii") + b" " + str(len(raw)).encode("ascii")
                        + b"\0" + raw, usedforsecurity=False).hexdigest()


def token_value(raw: object) -> str:
    require(type(raw) is str and re.fullmatch(r"[A-Za-z0-9_]{20,255}", raw) is not None,
            "TRANSPORT_CREDENTIAL_INVALID")
    return raw


def json_object(raw: bytes) -> dict:
    try:
        value = decode(raw)
        require(type(value) is dict, "TRANSPORT_PROTOCOL_FAILED")
        return value
    except Refusal as exc:
        raise TransportError("TRANSPORT_PROTOCOL_FAILED") from exc


def verified_tree(raw: bytes, expected: str) -> dict[str, dict]:
    """Rebuild a *nonrecursive* Git tree; never use returned URL fields."""
    value = json_object(raw)
    require(value.get("sha") == expected and value.get("truncated") is False,
            "TRANSPORT_TREE_INVALID")
    entries = value.get("tree")
    require(type(entries) is list and len(entries) <= MAX_TREE_ENTRIES,
            "TRANSPORT_TREE_INVALID")
    result = {}
    modes = {"100644": "blob", "100755": "blob", "120000": "blob",
             "040000": "tree", "160000": "commit"}
    for entry in entries:
        require(type(entry) is dict, "TRANSPORT_TREE_INVALID")
        name, mode = entry.get("path"), entry.get("mode")
        require(type(name) is str and 0 < len(name.encode("utf-8")) <= 255
                and "/" not in name and "\0" not in name and name not in (".", "..")
                and name not in result, "TRANSPORT_TREE_INVALID")
        require(type(mode) is str and mode in modes and entry.get("type") == modes[mode],
                "TRANSPORT_TREE_INVALID")
        oid(entry.get("sha"))
        result[name] = entry
    ordered = sorted(result.values(), key=lambda e: (e["path"] + ("/" if e["mode"] == "040000" else "")).encode("utf-8"))
    body = b"".join(e["mode"].lstrip("0").encode("ascii") + b" "
                    + e["path"].encode("utf-8") + b"\0" + bytes.fromhex(e["sha"])
                    for e in ordered)
    require(git_oid("tree", body) == expected, "TRANSPORT_TREE_HASH_MISMATCH")
    return result


def entry_at(tree: dict[str, dict], name: str, mode: str) -> dict:
    require(name in tree, "TRANSPORT_PATH_MISSING")
    entry = tree[name]
    require(entry["mode"] == mode, "TRANSPORT_FILE_MODE_REFUSED")
    return entry


def validate_snapshot(value: dict) -> dict:
    """Validate the trusted helper receipt again at publication/replay boundaries."""
    try:
        raw = canonical(value)
        require(len(raw) <= MAX_SNAPSHOT_BYTES, "TRANSPORT_SNAPSHOT_INVALID")
        value = decode(raw)  # detach from mutable caller objects, bound complexity
        require(type(value) is dict and set(value) == {"slots", "provenance"},
                "TRANSPORT_SNAPSHOT_INVALID")
        require(type(value["slots"]) is list and len(value["slots"]) == 4,
                "TRANSPORT_SNAPSHOT_INVALID")
        values = [slot(canonical(v), n) for n, v in enumerate(value["slots"], 1)]
        check(value["provenance"], "slot-source-v1.schema.json")
        proof = value["provenance"]
        require(proof["slots_digest"] == digest(values), "TRANSPORT_SNAPSHOT_INVALID")
        for n, (data, record) in enumerate(zip(values, proof["files"]), 1):
            require(record["path"] == f"slots/slot{n}.json"
                    and record["value_sha256"] == digest(data), "TRANSPORT_SNAPSHOT_INVALID")
        return {"slots": values, "provenance": proof}
    except (Refusal, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        if isinstance(exc, TransportError):
            raise
        raise TransportError("TRANSPORT_SNAPSHOT_INVALID") from exc


def collect_snapshot(read: Callable[..., bytes]) -> dict:
    """Exactly eight fixed-path reads, one ref resolution, no state writes."""
    ref = json_object(read(REF_PATH))
    require(ref.get("ref") == SOURCE_REF and type(ref.get("object")) is dict,
            "TRANSPORT_REF_MISMATCH")
    require(ref["object"].get("type") == "commit", "TRANSPORT_REF_MISMATCH")
    commit_sha = oid(ref["object"].get("sha"))
    commit = json_object(read(PREFIX + "commits/" + commit_sha))
    require(commit.get("sha") == commit_sha and type(commit.get("tree")) is dict,
            "TRANSPORT_COMMIT_MISMATCH")
    root_sha = oid(commit["tree"].get("sha"))
    root = verified_tree(read(PREFIX + "trees/" + root_sha), root_sha)
    slots_sha = entry_at(root, "slots", "040000")["sha"]
    tree = verified_tree(read(PREFIX + "trees/" + slots_sha), slots_sha)
    raw_slots, records = [], []
    for n in range(1, 5):
        entry = entry_at(tree, f"slot{n}.json", "100644")
        size = entry.get("size")
        require(type(size) is int and 0 <= size <= MAX_BYTES, "TRANSPORT_RESPONSE_LIMIT")
        blob_sha = entry["sha"]
        raw = read(PREFIX + "blobs/" + blob_sha, raw=True)
        require(type(raw) is bytes and len(raw) <= MAX_BYTES, "TRANSPORT_RESPONSE_LIMIT")
        require(len(raw) == size and git_oid("blob", raw) == blob_sha,
                "TRANSPORT_BLOB_MISMATCH")
        raw_slots.append(raw)
        records.append({"path": f"slots/slot{n}.json", "blob_sha": blob_sha,
                        "bytes": len(raw), "content_sha256": hashlib.sha256(raw).hexdigest()})
    try:
        values = [slot(raw, n) for n, raw in enumerate(raw_slots, 1)]
    except Refusal as exc:
        raise TransportError("REMOTE_SLOT_SCHEMA_INVALID") from exc
    for record, data in zip(records, values):
        record["value_sha256"] = digest(data)
    return validate_snapshot({"slots": values, "provenance": {
        "contract_version": CONTRACT, "source_id": SOURCE_ID,
        "repository": REPOSITORY, "ref": SOURCE_REF, "commit_sha": commit_sha,
        "root_tree_sha": root_sha, "slots_tree_sha": slots_sha,
        "slots_digest": digest(values), "files": records,
    }})


def _connection(timeout: float, context: ssl.SSLContext):
    return http.client.HTTPSConnection(HOST, 443, timeout=timeout, context=context)


class GitHubReader:
    """Direct TLS, fixed origin, no proxies/netrc/helpers/redirects/retries."""
    def __init__(self, token: str):
        self._token = token_value(token)
        self._deadline = time.monotonic() + NETWORK_SECONDS
        self._requests = 0
        self._context = ssl.create_default_context()

    def remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        require(remaining > 0, "TRANSPORT_TIMEOUT")
        return min(5, remaining)

    def __call__(self, path: str, *, raw: bool = False) -> bytes:
        suffix = path.removeprefix(PREFIX) if type(path) is str else ""
        require(path == REF_PATH or (type(path) is str and path.startswith(PREFIX)
                and re.fullmatch(r"(?:commits|trees|blobs)/[0-9a-f]{40}", suffix) is not None),
                "TRANSPORT_PATH_REFUSED")
        require(raw == suffix.startswith("blobs/"), "TRANSPORT_PATH_REFUSED")
        self._requests += 1
        require(self._requests <= MAX_REQUESTS, "TRANSPORT_REQUEST_LIMIT")
        conn = None
        try:
            conn = _connection(self.remaining(), self._context)
            conn.request("GET", path, headers={
                "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
                "Accept-Encoding": "identity", "Authorization": "Bearer " + self._token,
                "User-Agent": "techrote-ansible-slot-transport-v1",
                "X-GitHub-Api-Version": API_VERSION, "Connection": "close",
            })
            response = conn.getresponse()
            self.remaining()
            code = response.status
            require(not 300 <= code <= 399, "TRANSPORT_REDIRECT_REFUSED")
            require(code not in (401, 403), "TRANSPORT_AUTH_FAILED")
            require(code != 404, "TRANSPORT_NOT_FOUND")
            require(code != 429, "TRANSPORT_RATE_LIMITED")
            require(code == 200, "TRANSPORT_HTTP_FAILED")
            require(response.getheader("Content-Encoding", "identity").lower() == "identity",
                    "TRANSPORT_PROTOCOL_FAILED")
            lengths = [v for k, v in response.getheaders() if k.lower() == "content-length"]
            require(len(lengths) <= 1, "TRANSPORT_PROTOCOL_FAILED")
            length = None
            if lengths:
                require(re.fullmatch(r"[0-9]{1,6}", lengths[0]) is not None,
                        "TRANSPORT_RESPONSE_LIMIT")
                length = int(lengths[0])
                require(length <= MAX_BYTES, "TRANSPORT_RESPONSE_LIMIT")
            data = bytearray()
            while True:
                self.remaining()
                chunk = response.read1(min(8192, MAX_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                require(len(data) <= MAX_BYTES, "TRANSPORT_RESPONSE_LIMIT")
            self.remaining()
            require(length is None or len(data) == length, "TRANSPORT_PROTOCOL_FAILED")
            return bytes(data)
        except TransportError:
            raise
        except TimeoutError as exc:
            raise TransportError("TRANSPORT_TIMEOUT") from exc
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise TransportError("TRANSPORT_IO_FAILED") from exc
        finally:
            if conn is not None:
                conn.close()


def fetch_remote_snapshot(token: str) -> dict:
    """Supervise fixed nonforking helper so DNS/slow headers cannot hang the CLI."""
    token = token_value(token)
    root = Path(__file__).resolve().parent.parent
    process, job, captures = None, None, []
    overflow = threading.Event()
    try:
        if os.name == "nt":
            job = WindowsJob(256, 2)
        elif not sys.platform.startswith("linux"):
            raise TransportError("TRANSPORT_PLATFORM_UNQUALIFIED")
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", str(root / "run_slot_transport.py"), str(os.getpid())],
            cwd=root, env=clean_environment(root), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, close_fds=True,
            start_new_session=os.name == "posix", creationflags=0x08000000 if os.name == "nt" else 0)
        if job is not None:
            job.assign(process)
        captures = [Capture(process.stdout, overflow, limit=MAX_BYTES),
                    Capture(process.stderr, overflow, limit=4096)]
        process.stdin.write(token.encode("ascii") + b"\n")
        process.stdin.close()
        deadline = time.monotonic() + HELPER_SECONDS
        while process.poll() is None:
            require(not overflow.is_set(), "TRANSPORT_OUTPUT_LIMIT")
            require(time.monotonic() < deadline, "TRANSPORT_TIMEOUT")
            time.sleep(0.01)
        stdout, stderr = [capture.finish() for capture in captures]
        require(not overflow.is_set(), "TRANSPORT_OUTPUT_LIMIT")
        require(not stderr, "TRANSPORT_HELPER_FAILED")
        reply = json_object(stdout)
        if (set(reply) == {"error"} and type(reply["error"]) is str
                and reply["error"] in ERRORS and process.returncode != 0):
            raise TransportError(reply["error"])
        require(process.returncode == 0, "TRANSPORT_HELPER_FAILED")
        return validate_snapshot(reply)
    except TransportError:
        raise
    except KeyboardInterrupt as exc:
        raise TransportError("TRANSPORT_INTERRUPTED") from exc
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise TransportError("TRANSPORT_HELPER_FAILED") from exc
    finally:
        try:
            if process is not None:
                terminate(process, job)
                process.wait(timeout=2)
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if captures:
                    for capture in captures:
                        capture.finish()
                else:
                    for stream in (process.stdout, process.stderr):
                        if stream:
                            stream.close()
        finally:
            if job is not None:
                job.close()


def helper_main() -> int:
    # Credentials arrive only after the parent's Windows Job assignment. Linux
    # applies the existing fixed-child resource/parent-death guards first.
    try:
        if len(sys.argv) != 2:
            raise TransportError("TRANSPORT_HELPER_FAILED")
        if sys.platform.startswith("linux"):
            from .worker import apply_linux_limits
            apply_linux_limits(256, 2, int(sys.argv[1]))
        elif os.name != "nt":
            raise TransportError("TRANSPORT_PLATFORM_UNQUALIFIED")
        raw = sys.stdin.buffer.read(257)
        token = token_value(raw.removesuffix(b"\n").decode("ascii"))
        value = collect_snapshot(GitHubReader(token))
        sys.stdout.buffer.write(canonical(value) + b"\n")
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, TransportError) else "TRANSPORT_HELPER_FAILED"
        # No exception messages, response bodies or credential fields are emitted.
        sys.stdout.buffer.write(canonical({"error": code}) + b"\n")
        return 3
