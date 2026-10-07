"""Cerberus 8.3 -- fails if generate_bulk_payments.py's roster drifts from payments_lib.

The Spark generator carries a hand-copied roster because its image has no
Faker (ADR 0018). This compares that copy with payments_lib.build_roster(),
the roster every Lambda-written bronze event uses. The generator file is
parsed with ast, not imported, so this check needs no PySpark -- only
ingestion/requirements.txt (Faker, at the same pin as the Lambda layer).

    uv run --no-project --with-requirements ingestion/requirements.txt \
        python transform/spark/check_bulk_roster.py
"""

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / "transform/spark/generate_bulk_payments.py"
sys.path.insert(0, str(REPO / "ingestion/scripts"))

from payments_lib import build_roster  # noqa: E402


def literal(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise SystemExit(f"{name} not found in {GENERATOR}")


def main():
    tree = ast.parse(GENERATOR.read_text())
    merchants, customers = build_roster()
    expected = {
        "MERCHANTS": [(m["merchant_id"], m["name"], m["category"]) for m in merchants],
        "CUSTOMERS": [(c["customer_id"], c["name"], c["email"]) for c in customers],
    }
    failed = False
    for name, rows in expected.items():
        copied = literal(tree, name)
        if copied != rows:
            failed = True
            print(f"DRIFT: {name} differs from payments_lib.build_roster()")
        else:
            print(f"ok: {name} matches ({len(rows)} rows)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
