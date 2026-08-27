"""Cerberus 6.1 — data-freshness probe (Phase 6, Observability & data quality).

An hourly EventBridge Scheduler-triggered Lambda that measures how stale the
pipeline's outputs are and publishes the answer as CloudWatch custom metrics,
so the observability dashboard (and 6.2's alarms) have a real "seconds since …"
number to show and threshold.

CloudWatch has no native "time since last write" metric, and CloudWatch
dashboard metric math has no now() function — so this value cannot be derived
from the pipeline's own emitted metrics alone. It needs an external observer
running on its own clock. This Lambda is that observer.

Three signals, published as Cerberus/Pipeline -> FreshnessSeconds with a
Signal dimension:

  PipelineRun  seconds since the orchestration state machine last reached a
               SUCCEEDED execution — the primary health signal; the daily
               EventBridge run should keep this under ~25h.
  BronzeData   seconds since the newest object under bronze payments/ was
               written. Note the scheduled generator self-retired 2026-08-17
               (ADR 0005), so this grows until generate_payments.py is next
               run by hand — expected, not a fault.
  GoldData     seconds since the newest object anywhere in the gold bucket was
               written (dbt marts plus the 1.7 current-state table).

Runs as its own least-privilege execution role (cerberus-freshness-probe,
defined in terraform/modules/observability, not terraform/modules/iam — same
self-contained pattern step_functions uses for its scheduler role). Read-only
everywhere except cloudwatch:PutMetricData, which is constrained by a
namespace condition.
"""

import os
from datetime import UTC, datetime

import boto3

NAMESPACE = "Cerberus/Pipeline"
METRIC_NAME = "FreshnessSeconds"

STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]
BRONZE_BUCKET = os.environ["BRONZE_BUCKET"]
BRONZE_PREFIX = os.environ.get("BRONZE_PREFIX", "payments/")
GOLD_BUCKET = os.environ["GOLD_BUCKET"]

_sfn = boto3.client("stepfunctions")
_s3 = boto3.client("s3")
_cw = boto3.client("cloudwatch")


def _last_successful_execution_time():
    """stopDate of the most recent SUCCEEDED execution, or None if there is none.

    list_executions returns results most-recent-first, so maxResults=1 with the
    SUCCEEDED filter is exactly the last good run.
    """
    resp = _sfn.list_executions(
        stateMachineArn=STATE_MACHINE_ARN,
        statusFilter="SUCCEEDED",
        maxResults=1,
    )
    executions = resp.get("executions", [])
    if not executions:
        return None
    return executions[0]["stopDate"]


def _newest_object_time(bucket, prefix):
    """LastModified of the newest object under bucket/prefix, or None if empty."""
    newest = None
    for page in _s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if newest is None or obj["LastModified"] > newest:
                newest = obj["LastModified"]
    return newest


def _age_seconds(then, now):
    if then is None:
        return None
    return max(0.0, (now - then).total_seconds())


def handler(event, context):
    now = datetime.now(UTC)

    signals = {
        "PipelineRun": _age_seconds(_last_successful_execution_time(), now),
        "BronzeData": _age_seconds(_newest_object_time(BRONZE_BUCKET, BRONZE_PREFIX), now),
        "GoldData": _age_seconds(_newest_object_time(GOLD_BUCKET, ""), now),
    }

    metric_data = [
        {
            "MetricName": METRIC_NAME,
            "Dimensions": [{"Name": "Signal", "Value": name}],
            "Timestamp": now,
            "Value": age,
            "Unit": "Seconds",
        }
        for name, age in signals.items()
        if age is not None
    ]

    if metric_data:
        _cw.put_metric_data(Namespace=NAMESPACE, MetricData=metric_data)

    reported = {name: round(age) for name, age in signals.items() if age is not None}
    missing = [name for name, age in signals.items() if age is None]

    line = f"[{now.isoformat()}] freshness seconds: {reported}"
    if missing:
        line += f"; no data for: {missing}"
    print(line)

    return {"reported": reported, "missing": missing}
