"""Trusted bootstrap. Invoke with python -I -S -B to exclude ambient imports."""
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Ansible kernel requires Python 3.12 or newer.")
if not sys.flags.isolated or not sys.flags.no_site:
    raise SystemExit("Use python -I -S -B run_kernel.py to exclude ambient imports.")
from pathlib import Path

# This path is derived from trusted installed code, never from a request/cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ansible_kernel.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
