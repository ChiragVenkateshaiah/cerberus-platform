#!/usr/bin/env bash
# Publish the built landing page to the standing edge (ADR 0024; plan
# docs/plans/2026-11-09-landing-page-publish.md).
#
# Usage: publish_site.sh DIR BUCKET DIST_ID URL
#
# Runs in CI (.github/workflows/console-site.yml) and as the owner fallback
# (make console-site-publish). It never echoes the bucket name, never mirrors
# the folder and never passes a bulk-delete flag: it deletes
# only the stale hashed files that cerberus_landing.publish says the builder
# owns, and only after the invalidation completes. healthz.txt and live.json
# are never touched.
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: $0 DIR BUCKET DIST_ID URL" >&2
  exit 2
fi
for a in "$1" "$2" "$3" "$4"; do [ -n "$a" ] || { echo "publish failed: empty argument" >&2; exit 2; }; done
DIR="$1"
BUCKET="$2"
DIST="$3"
URL="${4%/}"
HERE="$(cd "$(dirname "$0")" && pwd)"

IMMUTABLE="public, max-age=31536000, immutable"
S3_FLAGS=(--no-progress --only-show-errors)

fail() {
  echo "publish failed: $*" >&2
  exit 1
}

# 1. The build id comes from the page's own meta tag.
[ -f "$DIR/index.html" ] || fail "$DIR/index.html is missing; run make console-site"
BUILD_ID="$(sed -n 's/.*<meta name="cerberus-build" content="\([0-9a-f]\{64\}\)".*/\1/p' "$DIR/index.html" | head -n 1)"
[ -n "$BUILD_ID" ] || fail "no 64-hex cerberus-build meta tag in index.html"

# 2. Stylesheet.
for f in "$DIR"/site.*.css; do
  [ -f "$f" ] || fail "no site.*.css in $DIR"
  aws s3 cp "$f" "s3://$BUCKET/$(basename "$f")" "${S3_FLAGS[@]}" \
    --content-type "text/css; charset=utf-8" --cache-control "$IMMUTABLE"
done

# 3. Favicon and charts.
for f in "$DIR"/favicon.*.svg "$DIR"/img/*.svg; do
  [ -f "$f" ] || continue
  key="${f#"$DIR"/}"
  aws s3 cp "$f" "s3://$BUCKET/$key" "${S3_FLAGS[@]}" \
    --content-type "image/svg+xml" --cache-control "$IMMUTABLE"
done

# 4. The page goes last, so it never points at a file that is not there yet.
aws s3 cp "$DIR/index.html" "s3://$BUCKET/index.html" "${S3_FLAGS[@]}" \
  --content-type "text/html; charset=utf-8" --cache-control "no-cache"

# 5. One wildcard path (free within 1,000 a month); wait until it is done.
INV="$(aws cloudfront create-invalidation --distribution-id "$DIST" --paths '/*' \
  --query 'Invalidation.Id' --output text)"
aws cloudfront wait invalidation-completed --distribution-id "$DIST" --id "$INV"

# 6. Delete stale builder-owned keys, after the invalidation.
REMOTE="$(aws s3api list-objects-v2 --bucket "$BUCKET" --query 'Contents[].Key' --output json)"
HAD_LIVE=0
if [[ "$REMOTE" == *'"live.json"'* ]]; then HAD_LIVE=1; fi
STALE="$(printf '%s' "$REMOTE" | PYTHONPATH="$HERE" python3 -m cerberus_landing stale --dir "$DIR")"
if [ -n "$STALE" ]; then
  while IFS= read -r key; do
    aws s3 rm "s3://$BUCKET/$key" "${S3_FLAGS[@]}"
  done <<<"$STALE"
fi

# 7. Checks against the public URL.
HDR="$(mktemp)"
BODY="$(mktemp)"
trap 'rm -f "$HDR" "$BODY"' EXIT

curl -fsS -D "$HDR" -o "$BODY" "$URL/"
grep -qi '^content-security-policy:' "$HDR" || fail "no CSP header on $URL/"
grep -qi '^cache-control:.*no-cache' "$HDR" || fail "no no-cache header on $URL/"
grep -q "content=\"$BUILD_ID\"" "$BODY" || fail "the live page is not build ${BUILD_ID:0:12}"

curl -fsS -o /dev/null "$URL/healthz.txt" || fail "healthz.txt does not return 200"

CSS="$(grep -o 'site\.[0-9a-f]\{10\}\.css' "$BODY" | head -n 1 || true)"
[ -n "$CSS" ] || fail "index.html names no stylesheet"
curl -fsS -D "$HDR" -o /dev/null "$URL/$CSS"
grep -qi '^cache-control:.*immutable' "$HDR" || fail "$CSS is not immutable"
grep -qi '^content-type:.*text/css' "$HDR" || fail "$CSS is not text/css"

if [ "$HAD_LIVE" -eq 1 ]; then
  aws s3api head-object --bucket "$BUCKET" --key live.json >/dev/null || fail "live.json is gone"
fi

echo "published build ${BUILD_ID:0:12}"
