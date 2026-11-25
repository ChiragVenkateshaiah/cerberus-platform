import sys
from pathlib import Path

# data_quality_downloads.py is a script next to this directory, not a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
