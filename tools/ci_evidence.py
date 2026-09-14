"""Trusted CI reporting only; never imported by the execution kernel."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
REPORTS = {"tests": "unittest.txt", "qualify": "qualification.json"}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def capture(mode: str, root: Path = ROOT) -> int:
    """Keep stdout/stderr separately so qualification remains valid JSON."""
    commands = {
        "tests": [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
        "qualify": [sys.executable, "-I", "-S", "-B", "run_kernel.py", "qualify"],
    }
    if mode not in commands:
        raise ValueError("Unknown verification mode")
    directory = root / "ci-evidence"
    directory.mkdir(exist_ok=True)
    stdout_path = directory / REPORTS[mode]
    stderr_path = directory / (mode + ".stderr.txt")
    code = 1
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            completed = subprocess.run(commands[mode], cwd=root, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, shell=False, timeout=480)
            code = completed.returncode
        except subprocess.TimeoutExpired:
            stderr.write(b"CI verification exceeded its 480 second deadline.\n")
            code = 124
        except OSError:
            stderr.write(b"CI verification could not start.\n")
            code = 125
    write_json(directory / (mode + ".exit.json"), {"mode": mode, "exit_code": code})
    for path, stream in ((stdout_path, sys.stdout), (stderr_path, sys.stderr)):
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stream.write(line)
    return code


def safe_sha(value: str) -> str | None:
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def bundle(root: Path = ROOT) -> None:
    """Archive HEAD, not the working directory or .git/credential metadata."""
    directory = root / "ci-evidence"
    directory.mkdir(exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if safe_sha(head) is None:
        raise ValueError("Invalid checkout SHA")
    # A dirty tracked checkout would make an archive of HEAD misleading evidence.
    subprocess.run(["git", "diff", "--no-ext-diff", "--exit-code", "HEAD", "--"],
                   cwd=root, check=True, stdout=subprocess.DEVNULL, timeout=30)
    subprocess.run(["git", "archive", "--format=tar", "--output=" + str(directory / "source.tar"), head],
                   cwd=root, check=True, timeout=30)
    write_json(directory / "provenance.json", {
        "schema": "ansible.ci-evidence.v1", "checkout_sha": head,
        "requested_head_sha": safe_sha(os.environ.get("ANSIBLE_CI_HEAD_SHA", "")),
        "python": platform.python_version(), "platform": platform.system(),
        "machine": platform.machine(), "source_format": "git-archive-tar",
        "scope": "trusted-noop-only", "real_agent_qualified": False,
    })
    # Fixed names, never include arbitrary files created by tests or local secrets.
    names = ["source.tar", "provenance.json",
             "isolation-linux-bwrap.json", "isolation-composition.json",
             "isolation-platform.json"]
    for mode, report in REPORTS.items():
        names.extend([report, mode + ".stderr.txt", mode + ".exit.json"])
    hashes = {}
    for name in names:
        path = directory / name
        if path.is_file():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(directory / "checksums.json", hashes)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("tests", "qualify", "bundle"))
    args = parser.parse_args(argv)
    if args.mode == "bundle":
        bundle()
        return 0
    return capture(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
