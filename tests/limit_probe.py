"""Trusted test-only process; never registered as a production runner."""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ansible_kernel.worker import apply_linux_limits

mode = sys.argv[1]
if sys.platform.startswith("linux"):
    apply_linux_limits(128, 1, int(sys.argv[2]))
# Windows tests assign the Job Object before releasing this stdin gate.
if sys.stdin.buffer.read(1) != b"G":
    raise SystemExit(70)
if mode == "memory":
    try:
        value = bytearray(256 * 1024 * 1024)
    except MemoryError:
        raise SystemExit(42)
    raise SystemExit(43)
if mode == "cpu":
    print("cpu_probe_ready", flush=True)
    while True:
        pass
if mode == "sleep":
    print("ready", flush=True)
    time.sleep(30)
    raise SystemExit(0)
raise SystemExit(64)
