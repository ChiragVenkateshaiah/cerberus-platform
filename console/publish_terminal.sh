#!/usr/bin/env bash
# Publish the built terminal page to the standing edge (ADR 0024 amendment,
# 2026-11-12; plan docs/plans/2026-11-12-terminal-panel.md).
#
# Usage: publish_terminal.sh DIR BUCKET DIST_ID URL CLIENT_ID AUTH_DOMAIN
#
# Runs in CI (.github/workflows/console-terminal.yml) and as the owner fallback
# (make console-terminal-publish). It never echoes the bucket name, never mirrors
# the folder and never passes a bulk-delete flag: it deletes only the stale hashed
# files that cerberus_terminal.publish says the builder owns, one by one, and only
# after the invalidation completes. Everything outside terminal/ is never touched.
set -euo pipefail

if [ "$#" -ne 6 ]; then
  echo "usage: $0 DIR BUCKET DIST_ID URL CLIENT_ID AUTH_DOMAIN" >&2
  exit 2
fi
for a in "$1" "$2" "$3" "$4" "$5" "$6"; do [ -n "$a" ] || { echo "publish failed: empty argument" >&2; exit 2; }; done
DIR="$1"
BUCKET="$2"
DIST="$3"
URL="${4%/}"
CLIENT_ID="$5"
AUTH_DOMAIN="$6"
HERE="$(cd "$(dirname "$0")" && pwd)"

IMMUTABLE="public, max-age=31536000, immutable"
S3_FLAGS=(--no-progress --only-show-errors)

fail() {
  echo "publish failed: $*" >&2
  exit 1
}

# 1. The values that go in config.json must look right (the page checks them too).
[[ "$CLIENT_ID" =~ ^[a-z0-9]{1,128}$ ]] || fail "CLIENT_ID has an unexpected shape"
[[ "$AUTH_DOMAIN" =~ ^https://[a-z0-9-]+\.auth\.us-east-1\.amazoncognito\.com$ ]] \
  || fail "AUTH_DOMAIN has an unexpected shape"

# 2. The build id comes from the page's own meta tag.
[ -f "$DIR/terminal/index.html" ] || fail "$DIR/terminal/index.html is missing; run make console-terminal"
BUILD_ID="$(sed -n 's/.*<meta name="cerberus-build" content="\([0-9a-f]\{64\}\)".*/\1/p' "$DIR/terminal/index.html" | head -n 1)"
[ -n "$BUILD_ID" ] || fail "no 64-hex cerberus-build meta tag in terminal/index.html"

HDR="$(mktemp)"
BODY="$(mktemp)"
CONF="$(mktemp)"
trap 'rm -f "$HDR" "$BODY" "$CONF"' EXIT

# 3. Script and stylesheet.
for f in "$DIR"/terminal/terminal.*.js; do
  [ -f "$f" ] || fail "no terminal.*.js in $DIR/terminal"
  aws s3 cp "$f" "s3://$BUCKET/terminal/$(basename "$f")" "${S3_FLAGS[@]}" \
    --content-type "text/javascript; charset=utf-8" --cache-control "$IMMUTABLE"
done
for f in "$DIR"/terminal/terminal.*.css; do
  [ -f "$f" ] || fail "no terminal.*.css in $DIR/terminal"
  aws s3 cp "$f" "s3://$BUCKET/terminal/$(basename "$f")" "${S3_FLAGS[@]}" \
    --content-type "text/css; charset=utf-8" --cache-control "$IMMUTABLE"
done

# 4. The runtime config. It is written here, not built, so git never holds the client ID.
printf '{"client_id":"%s","auth_domain":"%s"}\n' "$CLIENT_ID" "$AUTH_DOMAIN" >"$CONF"
aws s3 cp "$CONF" "s3://$BUCKET/terminal/config.json" "${S3_FLAGS[@]}" \
  --content-type "application/json" --cache-control "no-cache"

# 5. The page goes last, so it never points at a file that is not there yet.
aws s3 cp "$DIR/terminal/index.html" "s3://$BUCKET/terminal/index.html" "${S3_FLAGS[@]}" \
  --content-type "text/html; charset=utf-8" --cache-control "no-cache"

# 6. One wildcard path under terminal/ (free within 1,000 a month); wait until it is done.
INV="$(aws cloudfront create-invalidation --distribution-id "$DIST" --paths '/terminal/*' \
  --query 'Invalidation.Id' --output text)"
aws cloudfront wait invalidation-completed --distribution-id "$DIST" --id "$INV"

# 7. Delete stale builder-owned keys, after the invalidation. Only under terminal/.
REMOTE="$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix terminal/ --query 'Contents[].Key' --output json)"
STALE="$(printf '%s' "$REMOTE" | PYTHONPATH="$HERE" python3 -m cerberus_terminal stale --dir "$DIR")"
if [ -n "$STALE" ]; then
  while IFS= read -r key; do
    aws s3 rm "s3://$BUCKET/$key" "${S3_FLAGS[@]}"
  done <<<"$STALE"
fi

# 8. Checks against the public URL.
curl -fsS -D "$HDR" -o "$BODY" "$URL/terminal/index.html"
grep -qi '^content-security-policy:' "$HDR" || fail "no CSP header on $URL/terminal/index.html"
grep -qi '^cache-control:.*no-cache' "$HDR" || fail "no no-cache header on $URL/terminal/index.html"
grep -q "content=\"$BUILD_ID\"" "$BODY" || fail "the live page is not build ${BUILD_ID:0:12}"

JS="$(grep -o 'terminal\.[0-9a-f]\{10\}\.js' "$BODY" | head -n 1 || true)"
[ -n "$JS" ] || fail "terminal/index.html names no script"
curl -fsS -D "$HDR" -o /dev/null "$URL/terminal/$JS"
grep -qi '^cache-control:.*immutable' "$HDR" || fail "$JS is not immutable"
grep -qi '^content-type:.*text/javascript' "$HDR" || fail "$JS is not text/javascript"

CSS="$(grep -o 'terminal\.[0-9a-f]\{10\}\.css' "$BODY" | head -n 1 || true)"
[ -n "$CSS" ] || fail "terminal/index.html names no stylesheet"
curl -fsS -D "$HDR" -o /dev/null "$URL/terminal/$CSS"
grep -qi '^content-type:.*text/css' "$HDR" || fail "$CSS is not text/css"

curl -fsS -o /dev/null "$URL/terminal/config.json" || fail "terminal/config.json does not return 200"

echo "published terminal build ${BUILD_ID:0:12}"
