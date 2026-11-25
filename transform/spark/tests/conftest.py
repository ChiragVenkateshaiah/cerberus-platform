import sys
from pathlib import Path

# generate_bulk_downloads.py is one file next to the tests' parent, not a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
