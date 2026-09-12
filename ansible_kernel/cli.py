"""Small local operator CLI/panel, not a project orchestrator or network API."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import CONTRACT, VERSION
from .contract import MAX_BYTES, REGISTRY, Refusal, canonical
from .kernel import Kernel, ROOT, fingerprint
from .state import Store, StateError, TERMINAL, read_bytes


def emit(value) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2))


def keypress():
    if os.name == "nt":
        import msvcrt
        return msvcrt.getwch().lower() if msvcrt.kbhit() else None
    import select
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.readline().strip().lower()
    return None


def panel(kernel: Kernel) -> int:
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        emit({"slots": kernel.slots(), "jobs": kernel.store.statuses()})
        return 0
    children, message = [], "Q leaves active jobs running."
    try:
        while True:
            jobs = kernel.store.statuses()
            active = [job for job in jobs if job["state"] not in TERMINAL]
            lines = ["Ansible | trusted local kernel | " + CONTRACT, ""]
            for value in kernel.slots():
                label = value["label"].encode("unicode_escape").decode("ascii")
                lines.append(f'{value["slot"]}: {value["state"]:5} g{value["generation"]} {label}')
            lines += ["", "Jobs (latest state transitions):"]
            for job in sorted(jobs, key=lambda x: x.get("time_ns", 0))[-8:]:
                result = job["result"] or {}
                lines.append(f'{job["job_id"]} {job["state"]} {result.get("worker_outcome", "")}')
            lines += ["", "1-4: launch | R: redraw cached data | C: cancel | X: contain | Q: leave",
                      "On Unix, press Enter after the key.", message]
            sys.stdout.write("\x1b[2J\x1b[H" + "\n".join(lines) + "\n")
            sys.stdout.flush()
            key = keypress()
            if key == "q":
                return 0
            if key in ("1", "2", "3", "4"):
                if active or any(child.poll() is None for child in children):
                    message = "Busy: this state root permits one active job."
                else:
                    command = [sys.executable, "-I", "-S", "-B", str(ROOT / "run_kernel.py"),
                               "--state-root", str(kernel.store.root), "run-slot", key]
                    children.append(subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                      shell=False, close_fds=True))
                    message = "Launch requested; the job journal records its outcome."
            elif key in ("c", "x") and active:
                message = kernel.store.control(active[-1]["job_id"], "cancel" if key == "c" else "contain")
            children = [child for child in children if child.poll() is None]
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Trusted, noop-only execution kernel")
    parser.add_argument("--state-root", type=Path, help="Trusted operator state directory, never task data")
    parser.add_argument("--expect-contract", default=CONTRACT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("contract")
    commands.add_parser("qualify")
    commands.add_parser("status")
    commands.add_parser("panel")
    commands.add_parser("recover")
    commands.add_parser("slots")
    commands.add_parser("run").add_argument("request_file", help="JSON file or - for stdin")
    commands.add_parser("run-slot").add_argument("number", type=int, choices=range(1, 5))
    commands.add_parser("refresh").add_argument("directory", type=Path)
    for name in ("cancel", "contain", "result", "export"):
        commands.add_parser(name).add_argument("job_id")
    args = parser.parse_args(argv)
    try:
        if args.expect_contract != CONTRACT:
            raise Refusal("INCOMPATIBLE_CONTRACT", "rejected_policy")
        if args.command == "contract":
            emit({"contract_version": CONTRACT, "implementation_version": VERSION,
                  "source_fingerprint": fingerprint(), "max_active_jobs_per_root": 1,
                  "runners": {key: {"enabled": value.enabled, "runner_contract": value.runner_contract,
                                    "provider_id": value.provider_id} for key, value in REGISTRY.items()},
                  "real_agent_qualified": False})
            return 0
        if args.command == "qualify":
            from .qualification import qualify
            report = qualify()
            emit(report)
            return 0 if report["profile_qualified"] else 1
        kernel = Kernel(Store(args.state_root))
        if args.command == "panel":
            return panel(kernel)
        if args.command == "run":
            raw = (sys.stdin.buffer.read(MAX_BYTES + 1) if args.request_file == "-"
                   else read_bytes(Path(args.request_file), MAX_BYTES + 1))
            result = kernel.execute(raw)
        elif args.command == "run-slot":
            result = kernel.run_slot(args.number)
        elif args.command in ("cancel", "contain"):
            emit({"job_id": args.job_id, "control_receipt": kernel.store.control(args.job_id, args.command)})
            return 0
        elif args.command == "result":
            result = kernel.store.result(args.job_id)
            if result is None:
                emit({"job_id": args.job_id, "result": None, "reason": "NO_TERMINAL_RESULT"})
                return 1
        elif args.command == "export":
            result = kernel.store.result(args.job_id)
            if result is None:
                raise StateError("NO_TERMINAL_RESULT")
            files = {}
            for name in ("metadata.json", "provider.json", "worker.json", "manifest.json", "status.jsonl"):
                try:
                    files[name] = read_bytes(kernel.store.job(args.job_id) / name).decode("utf-8")
                except FileNotFoundError:
                    pass
            emit({"snapshot_version": "ansible.evidence.v1", "job_id": args.job_id,
                  "verified_result": result, "files": files})
            return 0
        else:
            if args.command == "refresh":
                value = kernel.refresh(args.directory)
            elif args.command == "slots":
                value = kernel.slots()
            elif args.command == "recover":
                value = {"recovered_unknown_jobs": kernel.recover()}
            else:
                value = kernel.store.statuses()
            emit(value)
            return 0
        emit(result)
        return 0 if result["worker_outcome"] == "success" else (2 if result["admission"] != "admitted" else 1)
    except Refusal as exc:
        emit({"contract_version": CONTRACT, "error": exc.code, "admission": exc.admission})
        return 2
    except (StateError, OSError) as exc:
        emit({"contract_version": CONTRACT, "error": str(exc) if isinstance(exc, StateError) else "LOCAL_IO_FAILURE"})
        return 3
