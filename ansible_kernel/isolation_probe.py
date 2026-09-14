"""Fixed trusted probe executed only by linux_bwrap_v1 qualification."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def baseline(secret_path: str) -> int:
    report = {}
    report["input_read"] = Path("/input/readable.txt").read_text(encoding="ascii") == "visible\n"
    try:
        Path("/input/blocked.txt").write_text("bad", encoding="ascii")
        report["input_write_blocked"] = False
    except OSError:
        report["input_write_blocked"] = True
    try:
        Path(secret_path).read_bytes()
        report["host_secret_blocked"] = False
    except OSError:
        report["host_secret_blocked"] = True
    report["credential_env_absent"] = all(
        name not in os.environ for name in
        ("GH_TOKEN", "GITHUB_TOKEN", "AWS_ACCESS_KEY_ID", "SSH_AUTH_SOCK", "OPENAI_API_KEY")
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        sock.connect(("1.1.1.1", 53))
        report["network_blocked"] = False
    except OSError:
        report["network_blocked"] = True
    finally:
        sock.close()
    report["home_private"] = os.environ.get("HOME") == "/home/sandbox"
    report["pid_namespace"] = os.getpid() <= 4
    child = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c",
         "from pathlib import Path; Path('/output/child.txt').write_text('child\\n', encoding='ascii')"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=2, check=False)
    report["child_confined_write"] = child.returncode == 0 and Path("/output/child.txt").read_text(encoding="ascii") == "child\n"
    Path("/output/report.json").write_text(json.dumps(report, sort_keys=True), encoding="ascii")
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if all(report.values()) else 41


def main() -> int:
    if len(sys.argv) != 3:
        return 64
    mode, secret_path = sys.argv[1:]
    if mode == "baseline":
        return baseline(secret_path)
    if mode == "flood":
        os.write(1, b"X" * 1000000)
        time.sleep(30)
        return 0
    if mode == "hang":
        child = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", "import time; time.sleep(30)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Path("/output/ready").write_text(str(child.pid), encoding="ascii")
        time.sleep(30)
        return 0
    if mode == "memory":
        try:
            bytearray(1024 * 1024 * 1024)
        except MemoryError:
            print("memory_limited", flush=True)
            return 42
        return 43
    if mode == "cpu":
        print("cpu_probe_ready", flush=True)
        value = 0
        while True:
            value = (value + 1) & 0xffffffff
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
