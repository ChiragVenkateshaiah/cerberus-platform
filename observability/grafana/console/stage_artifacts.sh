#!/usr/bin/env bash
# Stage the pinned Grafana artifacts in the private artifacts/ prefix of the
# standing site bucket (step 10; plan docs/plans/2026-11-12-console-session.md).
#
# Usage: stage_artifacts.sh BUCKET
#
# Owner-run (make console-artifacts), once per version. For each entry in
# artifacts.json: skip it if the object already carries the pinned sha256 in
# its metadata; otherwise download, check sha256 and size, upload, and read
# the object back. It never echoes the bucket name, never syncs and never
# deletes in S3. Uses AWS_PROFILE and AWS_REGION from the environment.
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 BUCKET" >&2
  exit 2
fi
BUCKET="$1"
HERE="$(cd "$(dirname "$0")" && pwd)"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"

fail() {
  echo "stage failed: $*" >&2
  exit 1
}

WORK="$(mktemp -d)"
cleanup() {
  rm -rf "${WORK:?}"
}
trap cleanup EXIT

# One tab-separated line per artifact: name version url sha256 size key.
LINES="$(python3 -I - "$HERE/artifacts.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as f:
    doc = json.load(f)
for a in doc["artifacts"]:
    print("\t".join([a["name"], a["version"], a["url"], a["sha256"], str(a["size"]), a["key"]]))
PY
)"

# Prints "<ContentLength> <sha256 metadata>" for a key; non-zero if absent.
head_key() {
  aws s3api head-object --bucket "$BUCKET" --key "$1" \
    --query '[ContentLength, Metadata.sha256]' --output text 2>/dev/null
}

while IFS=$'\t' read -r NAME VERSION URL SHA SIZE KEY; do
  have="$(head_key "$KEY" || true)"
  if [ -n "$have" ] && [ "${have##*[[:space:]]}" = "$SHA" ]; then
    echo "$NAME $VERSION already staged"
    continue
  fi

  DIR="$(mktemp -d "$WORK/dl.XXXXXX")"
  FILE="$DIR/$(basename "$KEY")"
  echo "$NAME $VERSION downloading"
  curl -fsSL --proto '=https' -o "$FILE" "$URL" || fail "download of $NAME failed"
  got="$(sha256sum "$FILE" | cut -d' ' -f1)"
  [ "$got" = "$SHA" ] || fail "$NAME sha256 mismatch (got $got, pinned $SHA)"
  [ "$(stat -c %s "$FILE")" = "$SIZE" ] || fail "$NAME size differs from the pin ($SIZE)"

  aws s3 cp "$FILE" "s3://$BUCKET/$KEY" --no-progress --only-show-errors \
    --metadata "sha256=$SHA" --content-type application/octet-stream \
    || fail "upload of $NAME failed"

  back="$(head_key "$KEY" || true)"
  [ "${back%%[[:space:]]*}" = "$SIZE" ] || fail "$NAME ContentLength differs after upload"
  [ "${back##*[[:space:]]}" = "$SHA" ] || fail "$NAME metadata sha256 differs after upload"
  echo "$NAME $VERSION staged"
done <<<"$LINES"
