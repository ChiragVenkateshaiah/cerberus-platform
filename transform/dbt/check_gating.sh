#!/usr/bin/env bash
# 17.5: prove the downloads gating with real `dbt parse` runs (no warehouse
# connection: the CI profile has no credentials). Run from anywhere.
#
#   DBT="dbt"  (default)   or e.g. DBT="uv run --no-project --python 3.12 \
#                               --with-requirements requirements.txt dbt"
#
# default parse: no downloads model, source or test (the scheduled build is
# unchanged). Both vars true: all 5 models and both sources. enable_downloads
# only: the 3 silver models. enable_downloads_cdn alone: nothing (it needs
# enable_downloads too).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export DBT_PROFILES_DIR=ci_profiles
DBT="${DBT:-dbt}"

parse() { # parse MODE [dbt args...]
  local mode="$1"
  shift
  # shellcheck disable=SC2086
  $DBT parse --no-partial-parse "$@" >/dev/null
  python3 check_downloads_gating.py "$mode"
}

parse default
parse enabled --vars '{enable_downloads: true, enable_downloads_cdn: true}'
parse silver-only --vars '{enable_downloads: true}'
parse default --vars '{enable_downloads_cdn: true}'
