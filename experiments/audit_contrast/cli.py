"""python -m experiments.audit_contrast.cli"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.audit_contrast.run import main

if __name__ == "__main__":
    raise SystemExit(main())
