"""Import path for a bare `pytest agents/tests`: the package and the console package.

`make verify` and CI also set PYTHONPATH=agents:console; this line makes a bare
run work too.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("console", "agents"):
    path = str(ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)

# The shared hostile corpus lives in console/tests (hostile.py has no imports of its own).
_CORPUS = str(ROOT / "console" / "tests")
if _CORPUS not in sys.path:
    sys.path.append(_CORPUS)
