"""Cerberus 6.4b — OpenLineage event collector (Phase 6, lineage).

A single-purpose Lambda behind an API Gateway HTTP API. It receives
OpenLineage RunEvents (POST /api/v1/lineage, the Marquez-compatible path
the openlineage-spark listener and openlineage-dbt both emit to) and writes
each one verbatim to S3. That is the whole job — no database, no web UI, no
standing service. 6.4d reads the accumulated events back out of S3 and
renders the graph; ADR 0013 explains why this shape instead of Marquez or
Amazon DataZone.

The endpoint is deliberately unauthenticated (ADR 0013): its blast radius
is "write a JSON blob to a private, lifecycle-expiring S3 prefix", the
producers (Spark on EKS, dbt on Fargate) have no static credential to sign
with, and the API stage caps request rate. A malformed or hostile body is
stored under events/malformed/ rather than rejected outright, so a
producer-side schema drift is visible in S3 rather than silently dropped --
but it never fails the caller (a non-2xx would surface as a scary error in
the Spark driver log for something that must not break the pipeline).

Runs as its own least-privilege role (cerberus-lineage-collector, defined
in terraform/modules/lineage, not terraform/modules/iam -- same
self-contained pattern the freshness probe uses). s3:PutObject on
events/* and nothing else.
"""

import base64
import json
import os
import uuid
from datetime import UTC, datetime

import boto3

LINEAGE_BUCKET = os.environ["LINEAGE_BUCKET"]
EVENTS_PREFIX = os.environ.get("EVENTS_PREFIX", "events/")
# API Gateway HTTP APIs cap payloads at 10 MiB; a real OpenLineage event is
# a few KiB. Anything past this is not a lineage event we want to keep.
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", 1_048_576))

_s3 = boto3.client("s3")


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _raw_body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8")


def _slug(value, fallback):
    """Filesystem/S3-safe fragment for an object key."""
    keep = [c if (c.isalnum() or c in "-_.") else "-" for c in str(value or fallback)]
    return "".join(keep)[:120] or fallback


def _object_key(doc, now):
    """events/received_date=YYYY-MM-DD/<epoch_ms>-<namespace>-<job>-<eventType>-<short>.json

    Partitioned by receipt date (not event time) so 6.4d's reader and the
    lifecycle rule both work off a predictable prefix, and a late/replayed
    event still sorts next to when we actually saw it.
    """
    job = doc.get("job") or {}
    run = doc.get("run") or {}
    parts = [
        f"{int(now.timestamp() * 1000)}",
        _slug(job.get("namespace"), "ns"),
        _slug(job.get("name"), "job"),
        _slug(doc.get("eventType"), "event"),
        _slug(run.get("runId"), uuid.uuid4().hex)[:8],
    ]
    return f"{EVENTS_PREFIX}received_date={now:%Y-%m-%d}/{'-'.join(parts)}.json"


def _malformed_key(now):
    stamp = int(now.timestamp() * 1000)
    name = f"{stamp}-{uuid.uuid4().hex[:8]}.json"
    return f"{EVENTS_PREFIX}malformed/received_date={now:%Y-%m-%d}/{name}"


def handler(event, context):
    now = datetime.now(UTC)
    raw = _raw_body(event)

    if len(raw) > MAX_BODY_BYTES:
        print(f"[{now.isoformat()}] rejected oversized body ({len(raw)} bytes)")
        return _response(413, {"stored": False, "reason": "payload too large"})

    try:
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError("top-level JSON is not an object")
        key = _object_key(doc, now)
        malformed = False
    except ValueError as exc:
        key = _malformed_key(now)
        malformed = True
        print(f"[{now.isoformat()}] storing unparseable body under {key}: {exc}")

    _s3.put_object(
        Bucket=LINEAGE_BUCKET,
        Key=key,
        Body=raw,
        ContentType="application/json",
    )

    if not malformed:
        print(
            f"[{now.isoformat()}] stored {doc.get('eventType', '?')} event for "
            f"{(doc.get('job') or {}).get('name', '?')} -> s3://{LINEAGE_BUCKET}/{key}"
        )

    # Always 200: the caller (a Spark listener / dbt-ol) must never see a
    # lineage-transport failure as a pipeline error.
    return _response(200, {"stored": True, "key": key, "malformed": malformed})
