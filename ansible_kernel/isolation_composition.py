"""Host-only pinned snapshot -> Linux Bubblewrap composition qualification.

This module is deliberately not a runner and is never selected by execution/slot
wire data.  It proves that bytes materialized from an exact approved Git commit
can execute only behind the already qualified Linux Bubblewrap boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import tempfile
import uuid

from . import VERSION
from .contract import decode
from .config import KNOWN_REPOSITORIES
from . import isolation_bwrap as bwrap
from .snapshot import SnapshotManager
from .snapshot_common import SnapshotError, _repository
from .state import StateError, plain, read_bytes

CONTRACT = "ansible.isolation-composition.v1"
VERSION_NUMBER = 1
ENTRYPOINT = "ansible_sandbox_probe.py"
# SHA-256 of the trusted hostile fixture bytes in tests/fixtures/isolation_snapshot_probe.py.
# Runtime qualification is intentionally bound to these exact bytes: an arbitrary
# operator-selected commit may not substitute a self-reporting program at the fixed path.
TRUSTED_ENTRYPOINT_SHA256 = "f2af54591d9a45fb43418142dc4f1fd582d448108dafec19d48846a9dbcaec21"
MAX_ENTRYPOINT_BYTES = 128 * 1024
MAX_REPORT_BYTES = 16 * 1024
REQUIRED_BASELINE = (
    "input_read", "input_write_blocked", "host_secret_blocked",
    "credential_env_absent", "network_blocked", "home_private",
    "pid_namespace", "result_write", "child_confined_write",
)
REQUIRED_CHECKS = frozenset({
    "snapshot_filesystem_network_credentials_pid",
    "output_bound",
    "deadline_descendant_containment",
    "memory_limit",
    "cpu_limit",
    "snapshot_identity_preserved",
    "ownership_bounded_cleanup",
})


class CompositionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _private_root(path: Path, repository_path: Path) -> Path:
    path = Path(path)
    repo_input = Path(repository_path)
    if not path.is_absolute():
        raise CompositionError("STATE_ROOT_NOT_ABSOLUTE")
    if not repo_input.is_absolute():
        raise CompositionError("REPOSITORY_PATH_NOT_ABSOLUTE")
    try:
        plain(repo_input)
        repo = repo_input.resolve(strict=True)
        plain(repo)
        if not repo.is_dir():
            raise CompositionError("REPOSITORY_PATH_INVALID")
        # Resolve the prospective state path without creating it, then compare it
        # against the source and trusted-checkout boundaries in both directions.
        prospective = path.resolve(strict=False)
        trusted = Path(__file__).resolve().parent.parent
        for protected, code in ((repo, "STATE_ROOT_INSIDE_REPOSITORY"),
                                (trusted, "STATE_ROOT_INSIDE_TRUSTED_CHECKOUT")):
            try:
                prospective.relative_to(protected)
            except ValueError:
                pass
            else:
                raise CompositionError(code)
        try:
            repo.relative_to(prospective)
        except ValueError:
            pass
        else:
            raise CompositionError("REPOSITORY_INSIDE_STATE_ROOT")
        try:
            trusted.relative_to(prospective)
        except ValueError:
            pass
        else:
            raise CompositionError("TRUSTED_CHECKOUT_INSIDE_STATE_ROOT")
        plain(path)
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        plain(path)
        path = path.resolve(strict=True)
    except CompositionError:
        raise
    except (OSError, StateError) as exc:
        raise CompositionError("STATE_ROOT_INVALID") from exc
    if not path.is_dir():
        raise CompositionError("STATE_ROOT_INVALID")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise CompositionError("STATE_ROOT_PERMISSIONS_TOO_BROAD")
    return path


def _entrypoint(content: Path) -> tuple[Path, str]:
    path = content / ENTRYPOINT
    try:
        raw = read_bytes(path, MAX_ENTRYPOINT_BYTES)
        info = path.stat()
    except (OSError, StateError) as exc:
        raise CompositionError("COMPOSITION_ENTRYPOINT_INVALID") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not raw:
        raise CompositionError("COMPOSITION_ENTRYPOINT_INVALID")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != TRUSTED_ENTRYPOINT_SHA256:
        raise CompositionError("COMPOSITION_ENTRYPOINT_HASH_MISMATCH")
    return path, actual


def _build_command(mode: str, input_root: Path, output_root: Path,
                   secret_path: Path) -> list[str]:
    if mode not in bwrap.MODES:
        raise CompositionError("UNKNOWN_COMPOSITION_PROBE")
    entrypoint, _ = _entrypoint(Path(input_root))
    args = bwrap._boundary_command(input_root, output_root)
    return args + ["/usr/bin/python3", "-I", "-S", "-B",
                   "/input/" + entrypoint.name, mode, str(Path(secret_path).absolute())]


def _mechanism() -> dict:
    available = bwrap.availability()
    if not available.get("available"):
        return available
    executable = Path(available["bwrap_path"])
    digest = hashlib.sha256()
    total = 0
    with executable.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(chunk)
            if total > 64 * 1024 * 1024:
                raise CompositionError("BWRAP_BINARY_TOO_LARGE")
            digest.update(chunk)
    return {"available": True, "bwrap_version": available["bwrap_version"],
            "bwrap_sha256": digest.hexdigest(), "kernel": available["kernel"]}


def _report_file(path: Path) -> dict:
    try:
        value = decode(read_bytes(path, MAX_REPORT_BYTES))
    except (OSError, StateError, ValueError) as exc:
        raise CompositionError("COMPOSITION_REPORT_INVALID") from exc
    if type(value) is not dict or set(value) != set(REQUIRED_BASELINE):
        raise CompositionError("COMPOSITION_REPORT_INVALID")
    if not all(type(value[key]) is bool for key in REQUIRED_BASELINE):
        raise CompositionError("COMPOSITION_REPORT_INVALID")
    return value


def qualify(state_root: Path, repository_id: str, repository_path: Path,
            commit_sha: str) -> dict:
    """Qualify fixed hostile fixture bytes from one exact Git commit."""
    if type(repository_id) is not str or type(commit_sha) is not str:
        raise CompositionError("COMPOSITION_IDENTITY_INVALID")
    if re.fullmatch(r"[0-9a-f]{40}", commit_sha) is None:
        raise CompositionError("COMPOSITION_IDENTITY_INVALID")
    if repository_id not in KNOWN_REPOSITORIES:
        raise CompositionError("UNKNOWN_REPOSITORY_IDENTIFIER")
    repo = Path(repository_path)
    if not repo.is_absolute():
        raise CompositionError("REPOSITORY_PATH_NOT_ABSOLUTE")
    try:
        repo = _repository(repo)
    except SnapshotError as exc:
        raise CompositionError(exc.code) from exc
    root = _private_root(Path(state_root), repo)
    mechanism = _mechanism()
    from .kernel import fingerprint as runtime_fingerprint
    base = {"contract_version": CONTRACT, "composition_version": VERSION_NUMBER,
            "implementation_version": VERSION, "source_fingerprint": runtime_fingerprint(),
            "qualification_scope": "fixed_probe_commit", "platform": platform.system(),
            "repository_id": repository_id, "commit_sha": commit_sha,
            "profile_contract": bwrap.PROFILE_CONTRACT,
            "profile_fingerprint": bwrap.profile_fingerprint(),
            "expected_entrypoint_sha256": TRUSTED_ENTRYPOINT_SHA256,
            "runner_activation": False, "real_agent_qualified": False,
            "deployment_qualified": False, "mechanism": mechanism}
    if not mechanism.get("available"):
        return {**base, "composition_qualified": False, "checks": [],
                "reason": mechanism.get("reason", "PROFILE_UNAVAILABLE")}

    manager = SnapshotManager(root)
    job_id = uuid.uuid4().hex
    stage_root = root / "isolation-composition"
    try:
        plain(stage_root)
        stage_root.mkdir(mode=0o700, exist_ok=True)
        plain(stage_root)
        stage = Path(tempfile.mkdtemp(prefix="compose-", dir=stage_root))
        if os.name == "posix":
            os.chmod(stage, 0o700)
    except (OSError, StateError) as exc:
        raise CompositionError("COMPOSITION_STAGE_INVALID") from exc

    prepared = None
    checks: list[dict] = []
    snapshot_identity = None
    entrypoint_sha = None
    cleanup_ok = False
    try:
        try:
            prepared = manager.prepare(job_id, repository_id, repo, commit_sha)
            before = manager.verify(job_id, repository_id, commit_sha)
            content = Path(prepared["content_root"])
            _, entrypoint_sha = _entrypoint(content)
            snapshot_identity = {key: before[key] for key in (
                "snapshot_version", "repository_id", "commit_sha", "file_count",
                "total_bytes", "manifest_sha256")}
        except SnapshotError as exc:
            raise CompositionError("SNAPSHOT_PREPARATION_FAILED") from exc

        secret = stage / "host-secret.txt"
        secret.write_text("must-not-be-visible\n", encoding="ascii")
        if os.name == "posix":
            secret.chmod(0o600)

        def run_mode(mode: str, wall: float = bwrap.WALL_SECONDS) -> tuple[dict, Path]:
            out = stage / ("out-" + mode)
            out.mkdir(mode=0o700)
            command = _build_command(mode, content, out, secret)
            result = bwrap._run_command(mode, command, wall)
            # The input is immutable at the mount boundary, but content identity is
            # still revalidated by the trusted host after every adversarial mode.
            manager.verify(job_id, repository_id, commit_sha)
            return result, out

        baseline, output = run_mode("baseline")
        try:
            observed = _report_file(output / "report.json")
            baseline_ok = (baseline["returncode"] == 0
                           and baseline["termination"] == "natural"
                           and all(observed[key] for key in REQUIRED_BASELINE))
        except CompositionError:
            baseline_ok = False
        checks.append({"name": "snapshot_filesystem_network_credentials_pid", "passed": baseline_ok})

        flood, _ = run_mode("flood", 2.0)
        checks.append({"name": "output_bound", "passed": flood["termination"] == "output_limit"
                       and not flood["surviving_descendants"]})
        hang, _ = run_mode("hang", 0.75)
        checks.append({"name": "deadline_descendant_containment", "passed": hang["termination"] == "timeout"
                       and not hang["surviving_descendants"]})
        memory, _ = run_mode("memory", 3.0)
        checks.append({"name": "memory_limit", "passed": memory["returncode"] != 0
                       and memory["termination"] == "natural"})
        cpu, _ = run_mode("cpu", 4.0)
        checks.append({"name": "cpu_limit", "passed": cpu["returncode"] != 0
                       and b"cpu_probe_ready" in cpu["stdout"]
                       and cpu["termination"] == "natural"})

        final = manager.verify(job_id, repository_id, commit_sha)
        checks.append({"name": "snapshot_identity_preserved",
                       "passed": final == before})
        qualified = all(item["passed"] for item in checks)
    except (bwrap.IsolationError, SnapshotError, OSError, StateError) as exc:
        checks.append({"name": "composition_runtime", "passed": False,
                       "reason": getattr(exc, "code", "COMPOSITION_RUNTIME_FAILED")})
        qualified = False
    finally:
        if prepared is not None:
            try:
                cleanup_ok = manager.cleanup(job_id, repository_id, commit_sha)
            except SnapshotError:
                cleanup_ok = False
        # stage is host-created beneath a fixed root; rmtree does not follow
        # symlink directory entries and cannot target a model-provided path.
        try:
            plain(stage)
            shutil.rmtree(stage)
        except (OSError, StateError):
            cleanup_ok = False

    checks.append({"name": "ownership_bounded_cleanup", "passed": cleanup_ok})
    check_names = {item.get("name") for item in checks}
    qualified = (qualified and cleanup_ok
                 and check_names == REQUIRED_CHECKS
                 and len(checks) == len(REQUIRED_CHECKS)
                 and all(item.get("passed") is True for item in checks))
    return {**base, "composition_qualified": qualified,
            "snapshot": snapshot_identity, "entrypoint_sha256": entrypoint_sha,
            "limits": {"memory_mb": bwrap.MEMORY_MB,
                       "cpu_seconds": bwrap.CPU_SECONDS,
                       "wall_seconds": bwrap.WALL_SECONDS,
                       "capture_bytes_per_stream": bwrap.MAX_CAPTURE},
            "checks": checks, "reason": "QUALIFIED" if qualified else "CHECK_FAILED"}


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--repository-path", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    args = parser.parse_args(argv)
    try:
        value = qualify(args.state_root, args.repository_id, args.repository_path, args.commit_sha)
    except CompositionError as exc:
        value = {"contract_version": CONTRACT, "composition_qualified": False,
                 "runner_activation": False, "real_agent_qualified": False,
                 "reason": exc.code}
    print(json.dumps(value, sort_keys=True, indent=2))
    return 0 if value.get("composition_qualified") else 2
