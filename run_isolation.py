"""Trusted bootstrap for host isolation qualification only."""
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Ansible isolation qualification requires Python 3.12 or newer.")
if not sys.flags.isolated or not sys.flags.no_site:
    raise SystemExit("Use python -I -S -B run_isolation.py ... to exclude ambient imports.")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.argv[1:2] == ["compose-qualify"]:
    from ansible_kernel.isolation_composition import cli
    raise SystemExit(cli(sys.argv[2:]))

from ansible_kernel.isolation_bwrap import cli
if __name__ == "__main__":
    raise SystemExit(cli())
