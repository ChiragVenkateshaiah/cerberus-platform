#!/usr/bin/env bash
set -euo pipefail

# Cerberus 1.3 — scheduled-run wrapper for the payments generator.
#
# Cost/data control: the timer auto-retires after a fixed 10-day window
# instead of running indefinitely. Retiring means disabling
# cerberus-payments.timer, NOT deleting anything — generate_payments.py
# itself stays fully runnable by hand at any time; this wrapper only gates
# the *automatic* schedule, so it (not the generator) is where the
# retirement date lives.
#
# Window: first scheduled run 2026-08-07, last one 2026-08-16. On or after
# 2026-08-17 this disables the timer instead of generating.

REPO_ROOT="/home/chira/projects/cerberus"
RETIRE_ON_OR_AFTER="2026-08-17"
TODAY="$(date -u +%F)"

if [[ "$TODAY" < "$RETIRE_ON_OR_AFTER" ]]; then
  exec "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/ingestion/scripts/generate_payments.py" "$@"
fi

echo "[$(date -u +%FT%TZ)] retirement date reached ($RETIRE_ON_OR_AFTER) — disabling cerberus-payments.timer. Run generate_payments.py manually to add more data."
systemctl --user disable --now cerberus-payments.timer
