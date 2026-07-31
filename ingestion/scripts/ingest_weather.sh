#!/usr/bin/env bash
set -euo pipefail

# Cerberus Phase 0.4 — manual bash ingestion.
# Pulls current weather for a fixed set of cities from Open-Meteo (no API key
# required) and lands the raw JSON in the bronze bucket, Hive-partitioned by
# UTC date so Phase 2's Glue/Athena setup can read it without reshaping.

BUCKET="cerberus-platform-bronze-131715059025"
AWS_PROFILE="cerberus-admin"
AWS_REGION="us-east-1"

CITIES=(
  "new_york:40.7128:-74.0060"
  "london:51.5074:-0.1278"
  "tokyo:35.6762:139.6503"
  "bengaluru:12.9716:77.5946"
  "sydney:-33.8688:151.2093"
)

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DATE="$(date -u +%Y-%m-%d)"
TMPFILE="$(mktemp)"
trap 'rm -f "$TMPFILE"' EXIT

echo "[$(date -u +%FT%TZ)] starting weather ingestion run"

records="[]"
for city in "${CITIES[@]}"; do
  IFS=':' read -r name lat lon <<< "$city"
  response="$(curl -fsS "https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current_weather=true")"
  record="$(jq --arg city "$name" '{city: $city, current_weather: .current_weather}' <<< "$response")"
  records="$(jq --argjson r "$record" '. + [$r]' <<< "$records")"
  echo "[$(date -u +%FT%TZ)] fetched $name"
done

echo "$records" > "$TMPFILE"

S3_KEY="weather/dt=${DATE}/weather_${TIMESTAMP}.json"
aws s3 cp "$TMPFILE" "s3://${BUCKET}/${S3_KEY}" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --content-type application/json

echo "[$(date -u +%FT%TZ)] uploaded s3://${BUCKET}/${S3_KEY}"
