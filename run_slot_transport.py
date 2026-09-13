"""Fixed trusted data-fetch helper; the operator CLI supplies its credential pipe."""
import sys

if sys.version_info < (3, 12) or not sys.flags.isolated or not sys.flags.no_site:
    raise SystemExit("Use Python 3.12+ with -I -S -B.")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ansible_kernel.slot_transport import helper_main

if __name__ == "__main__":
    raise SystemExit(helper_main())
