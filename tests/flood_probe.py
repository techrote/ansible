"""Trusted adversarial-output test fixture, not a registered runner."""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ansible_kernel.worker import apply_linux_limits

if sys.platform.startswith("linux"):
    apply_linux_limits(*map(int, sys.argv[1:]))
sys.stdin.buffer.read(1025)
os.write(1, b"X" * 1000000)
time.sleep(10)
