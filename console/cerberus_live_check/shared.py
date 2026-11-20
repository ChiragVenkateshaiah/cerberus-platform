"""The expected values the harness shares with the test suite (one source, not a copy).

EDGE_HEADERS lives in tests/test_edge_config.py and the hostile inputs in
tests/hostile.py. Under pytest the tests directory is already on sys.path. From the
command line it is not, so it is added here, inside a function. test_edge_config.py
imports pytest at its top, so a live run needs `--with pytest` (the Makefile adds it).
"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1] / "tests"


def _ensure_tests_on_path() -> None:
    if str(TESTS_DIR) not in sys.path:
        sys.path.append(str(TESTS_DIR))


def edge_headers() -> dict[str, str]:
    _ensure_tests_on_path()
    import test_edge_config

    return dict(test_edge_config.EDGE_HEADERS)


def cognito_url() -> str:
    _ensure_tests_on_path()
    import test_edge_config

    return test_edge_config.COGNITO_URL


def hostile():
    _ensure_tests_on_path()
    import hostile as module

    return module
