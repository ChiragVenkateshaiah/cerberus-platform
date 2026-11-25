#!/usr/bin/env bash
# The standard offline checks for a change, in one command (make verify).
# No AWS, no git writes. It skips a check whose files do not exist on this
# branch, and it prints at most 15 lines of a failing check.
#
#   orchestration/verify.sh           ruff, tests, terraform fmt, shell syntax, scan
#   orchestration/verify.sh --full    also the Docker checks (alerts, e2e, render)
#
# VERIFY_BASE (default origin/main) is the base for the account-number scan.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 2
BASE="${VERIFY_BASE:-origin/main}"
FULL=0
[ "${1:-}" = "--full" ] && FULL=1

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
fail=0

check() { # check "name" command...
  local name="$1"
  shift
  if "$@" >"$LOG" 2>&1; then
    echo "ok    $name"
  else
    echo "FAIL  $name"
    tail -n 15 "$LOG"
    fail=1
  fi
}

skip() { echo "skip  $1 ($2)"; }

check "ruff check" uvx ruff@0.16.4 check -q .
check "ruff format" uvx ruff@0.16.4 format --check -q .

check "console tests" bash -c 'cd console && uv run --no-project --python 3.12 \
  --with pytest==9.1.1 --with PyYAML==6.0.3 python -m pytest -q'
check "verify_scan tests" uv run --no-project --python 3.12 \
  --with pytest==9.1.1 python -m pytest -q orchestration/test_verify_scan.py
check "agents tests" env PYTHONPATH=agents:console uv run --no-project --python 3.12 \
  --with pytest==9.1.1 python -m pytest -q agents/tests
check "status tests" uv run --no-project --python 3.12 \
  --with pytest==9.1.1 --with boto3==1.43.67 python -m pytest -q observability/status
check "grafana module tests (py3.9)" uv run --no-project --python 3.9 \
  --with "pytest>=8.4,<9" python -m pytest -q observability/grafana/console

if [ -f tools/traceability/generate.py ]; then
  check "traceability tests" uv run --no-project --python 3.12 \
    --with pytest==9.1.1 python -m pytest -q tools/traceability
  check "traceability record" python3 tools/traceability/generate.py --check
else
  skip "traceability" "not on this branch"
fi

if [ -f console/cerberus_landing/showcase.py ]; then
  check "showcase snapshot" make showcase-check
else
  skip "showcase snapshot" "not on this branch"
fi

if command -v terraform >/dev/null 2>&1; then
  check "terraform fmt" terraform fmt -check -recursive terraform
else
  skip "terraform fmt" "terraform not installed"
fi

# 17.3b (ADR 0030): the launch edge. validate needs the provider from the
# registry; node runs the Function and static tests. Each skips when its tool
# or the registry is unavailable.
if [ -d terraform/envs/dev-launch ]; then
  if command -v terraform >/dev/null 2>&1; then
    if terraform -chdir=terraform/envs/dev-launch init -backend=false -input=false >"$LOG" 2>&1; then
      check "terraform validate (dev-launch)" terraform -chdir=terraform/envs/dev-launch validate
    else
      skip "terraform validate (dev-launch)" "init failed: registry unavailable?"
    fi
  else
    skip "terraform validate (dev-launch)" "terraform not installed"
  fi
  if command -v node >/dev/null 2>&1; then
    check "launch edge node tests" node --test terraform/modules/launch_edge/function/license.test.mjs terraform/modules/launch_edge/static.test.mjs
  else
    skip "launch edge node tests" "node not installed"
  fi
fi

# Shell syntax of every shell script that changed or is new.
shell_files="$( (git diff --name-only "$BASE" -- '*.sh'; git ls-files -o --exclude-standard -- '*.sh') | sort -u)"
if [ -n "$shell_files" ]; then
  # shellcheck disable=SC2086,SC2016
  check "shell syntax" bash -c 'for f in "$@"; do bash -n "$f" || exit 1; done' _ $shell_files
else
  skip "shell syntax" "no shell script changed"
fi

check "account-number scan" python3 orchestration/verify_scan.py "$BASE"

if [ "$FULL" = 1 ]; then
  check "alert rules (Docker)" make alerts-test
  check "status e2e (Docker)" make status-e2e
  check "dashboard render (Docker)" make status-render
fi

if [ "$fail" = 0 ]; then
  echo "verify: all checks passed"
else
  echo "verify: FAILED"
fi
exit "$fail"
