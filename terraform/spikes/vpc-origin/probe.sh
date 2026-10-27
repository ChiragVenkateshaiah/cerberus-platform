#!/usr/bin/env bash
set -euo pipefail

# 9.2 VPC-origin spike -- HTTP and WebSocket probe. Read-only, curl only.
#
#   probe.sh DOMAIN_OR_BASE_URL
#
#   DOMAIN_OR_BASE_URL  a CloudFront domain (probed over https) or a full
#                       base URL such as http://127.0.0.1:8080 (local
#                       responder test: the same checks run against it).
#
# Polls "/" every POLL_INTERVAL seconds (default 10) up to POLL_MAX seconds
# (default 1200) and prints the seconds to the first 200 and every status
# code change. Then checks the body, that /nope is 404, and the WebSocket
# upgrade. Prints PASS or FAIL per check; exits 1 if any check fails.

TARGET="${1:?usage: probe.sh DOMAIN_OR_BASE_URL}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
POLL_MAX="${POLL_MAX:-1200}"

if [[ "$TARGET" == http://* || "$TARGET" == https://* ]]; then
  BASE="${TARGET%/}"
else
  BASE="https://$TARGET"
fi

FAILED=0
result() {
  if [[ "$1" == "PASS" ]]; then echo "PASS $2"; else echo "FAIL $2"; FAILED=1; fi
}

code_of() {
  local c
  c="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$@" 2>/dev/null || true)"
  # curl prints 000 itself on a connection failure; empty means no output.
  echo "${c:-000}"
}

start=$SECONDS
last=""
first_200=""
while :; do
  code="$(code_of "$BASE/")"
  elapsed=$((SECONDS - start))
  if [[ "$code" != "$last" ]]; then
    echo "t=${elapsed}s code=$code"
    last="$code"
  fi
  if [[ "$code" == "200" ]]; then
    first_200="$elapsed"
    break
  fi
  if ((elapsed + POLL_INTERVAL > POLL_MAX)); then
    break
  fi
  sleep "$POLL_INTERVAL"
done

if [[ -z "$first_200" ]]; then
  result FAIL "first HTTP 200 within ${POLL_MAX}s (last code $last)"
  exit 1
fi
result PASS "first HTTP 200 after ${first_200}s"

body="$(curl -sS --max-time 10 "$BASE/" || true)"
if [[ "$body" == "cerberus vpc-origin spike ok" ]]; then
  result PASS "body of /"
else
  result FAIL "body of /"
fi

nope="$(code_of "$BASE/nope")"
if [[ "$nope" == "404" ]]; then
  result PASS "/nope is 404"
else
  result FAIL "/nope is $nope (want 404)"
fi

# The server closes the connection after its frame; curl may exit non-zero
# (timeout on a held-open proxy connection), so ignore its exit code.
ws="$(curl --http1.1 -sS -i -N --max-time 5 \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  "$BASE/ws" 2>&1 || true)"
if grep -q 'HTTP/1.1 101' <<<"$ws"; then
  result PASS "WebSocket upgrade returns 101"
else
  result FAIL "WebSocket upgrade returns 101"
fi
if grep -qi 'Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=' <<<"$ws"; then
  result PASS "Sec-WebSocket-Accept value"
else
  result FAIL "Sec-WebSocket-Accept value"
fi

exit "$FAILED"
