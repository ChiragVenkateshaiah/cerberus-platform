# 6.2 (Phase 6 -- Observability & data quality): CloudWatch alarms +
# slow-job alerting, hung off the metrics 6.1 already put in place -- the
# AWS/States and AWS/Lambda metrics the pipeline publishes for free, and
# the Cerberus/Pipeline -> FreshnessSeconds{Signal} custom metrics the
# freshness probe publishes hourly.
#
# Delivery: one dedicated SNS topic (cerberus-pipeline-alerts) with an
# email subscription -- mirroring, not reusing, the Phase 0
# cerberus-billing-alerts topic, so a pipeline page and a cost page stay
# separate channels. Every alarm notifies on both ALARM and OK, so a
# resolved incident is visible from the inbox without opening the console.
#
# Gating (ADR 0011, amended 2026-09-01): the pipeline-health and
# data-freshness alarms are created only when var.pipeline_active = true --
# the same switch that ENABLEs the daily schedule. While dev-compute (EKS)
# is torn down, which is the normal state, the whole pipeline is dormant by
# design and every signal is legitimately stale; alarms on it then would
# fire every day for a non-problem. The two freshness-probe self-health
# alarms below are NOT gated -- the probe runs hourly regardless, and "the
# observer is broken" is always worth knowing.

locals {
  alerts_topic_name = "cerberus-pipeline-alerts"
}

resource "aws_sns_topic" "alerts" {
  name = local.alerts_topic_name
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Freshness-probe self-health (unconditional) --------------------
# If the probe stops working, every gated freshness alarm below silently
# goes stale-blind -- FreshnessSeconds just stops updating. These two are
# the alarms that catch that, so they exist regardless of pipeline_active.

# The probe ran and threw.
resource "aws_cloudwatch_metric_alarm" "probe_errors" {
  alarm_name        = "cerberus-freshness-probe-errors"
  alarm_description = "The cerberus-freshness-probe Lambda is erroring -- FreshnessSeconds metrics are not being refreshed. Check /aws/lambda/cerberus-freshness-probe."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = aws_lambda_function.probe.function_name }
  statistic   = "Sum"

  period              = 3600
  evaluation_periods  = 3
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  # Error metrics: absence means no errors, not missing information.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# The probe didn't run at all -- its hourly EventBridge Scheduler is broken
# or disabled. Dead-man switch: Lambda emits no Invocations datapoint for
# an hour with no invocation, so missing data is the breach signal.
resource "aws_cloudwatch_metric_alarm" "probe_silent" {
  alarm_name        = "cerberus-freshness-probe-silent"
  alarm_description = "The cerberus-freshness-probe Lambda has not run in ~3h -- its hourly EventBridge schedule (cerberus-freshness-probe-hourly) may be broken or disabled."

  namespace   = "AWS/Lambda"
  metric_name = "Invocations"
  dimensions  = { FunctionName = aws_lambda_function.probe.function_name }
  statistic   = "Sum"

  period              = 3600
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  # Heartbeat metric: a missing hour is exactly the fault we're watching
  # for. 3-of-3 so a single skipped/late invocation doesn't page.
  treat_missing_data = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# --- Pipeline health (only while a compute exercise is active) ------

# A daily run failed / timed out / was aborted. One metric-math alarm over
# all three unsuccessful terminal states rather than three near-identical
# alarms -- any of them means the same thing operationally.
resource "aws_cloudwatch_metric_alarm" "pipeline_run_unsuccessful" {
  count = var.pipeline_active ? 1 : 0

  alarm_name        = "cerberus-pipeline-run-unsuccessful"
  alarm_description = "A daily orchestration run failed, timed out, or was aborted. Check the state machine's execution history and the run's X-Ray trace."

  metric_query {
    id          = "unsuccessful"
    expression  = "failed + timedout + aborted"
    label       = "Unsuccessful executions"
    return_data = true
  }
  metric_query {
    id          = "failed"
    return_data = false
    metric {
      namespace   = "AWS/States"
      metric_name = "ExecutionsFailed"
      dimensions  = { StateMachineArn = var.state_machine_arn }
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id          = "timedout"
    return_data = false
    metric {
      namespace   = "AWS/States"
      metric_name = "ExecutionsTimedOut"
      dimensions  = { StateMachineArn = var.state_machine_arn }
      period      = 300
      stat        = "Sum"
    }
  }
  metric_query {
    id          = "aborted"
    return_data = false
    metric {
      namespace   = "AWS/States"
      metric_name = "ExecutionsAborted"
      dimensions  = { StateMachineArn = var.state_machine_arn }
      period      = 300
      stat        = "Sum"
    }
  }

  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# Slow-job alerting (Phases.md 6.2). Wall-clock duration of the run.
resource "aws_cloudwatch_metric_alarm" "pipeline_execution_slow" {
  count = var.pipeline_active ? 1 : 0

  alarm_name        = "cerberus-pipeline-execution-slow"
  alarm_description = "A daily orchestration run's ExecutionTime exceeded ${var.slow_execution_threshold_ms} ms. Use X-Ray to find which state is the bottleneck."

  namespace   = "AWS/States"
  metric_name = "ExecutionTime"
  dimensions  = { StateMachineArn = var.state_machine_arn }
  # Once-daily cadence: at most one execution per period, so Maximum is the
  # run's actual duration. p90/p99 (the usual latency-alarm statistic, to
  # avoid Average hiding tail latency) need a population this metric does
  # not have yet -- with one datapoint per run, Maximum is that datapoint.
  statistic = "Maximum"

  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = var.slow_execution_threshold_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# The ingestion Lambda errored. Raw count, not an error rate -- it is
# invoked exactly once per orchestrated run, so a rate is meaningless here.
resource "aws_cloudwatch_metric_alarm" "ingestion_errors" {
  count = var.pipeline_active ? 1 : 0

  alarm_name        = "cerberus-ingestion-errors"
  alarm_description = "The ingestion Lambda (${var.ingestion_lambda_name}) reported an error. Check /aws/lambda/${var.ingestion_lambda_name}."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = var.ingestion_lambda_name }
  statistic   = "Sum"

  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# --- Data freshness (only while a compute exercise is active) -------
# Thresholds on the probe's FreshnessSeconds{Signal} custom metrics.
#
# No BronzeData alarm: the ingestion Lambda is capped by
# RETIRE_ON_OR_AFTER=2026-08-17 in its own environment (ADR 0005), so it
# no-ops even when the schedule fires it inside an active exercise -- bronze
# does not refresh from the orchestrated run. Bronze freshness is therefore
# a manual-generation concern (run generate_payments.py, or bump the cap),
# not a pipeline-health signal, and the dashboard already frames it that
# way. PipelineRun and GoldData both do reflect a healthy active pipeline.

resource "aws_cloudwatch_metric_alarm" "freshness_pipeline_run" {
  count = var.pipeline_active ? 1 : 0

  alarm_name        = "cerberus-freshness-pipeline-run"
  alarm_description = "No SUCCEEDED orchestration run in over ${var.pipeline_run_freshness_threshold_seconds}s. Distinct from -run-unsuccessful: this also fires if the schedule stopped triggering entirely (no execution at all, failed or otherwise)."

  namespace   = "Cerberus/Pipeline"
  metric_name = "FreshnessSeconds"
  dimensions  = { Signal = "PipelineRun" }
  statistic   = "Maximum"

  period              = 3600
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = var.pipeline_run_freshness_threshold_seconds
  comparison_operator = "GreaterThanThreshold"
  # `missing`, not `breaching`: right after pipeline_active is flipped on
  # for a new exercise there may be no SUCCEEDED execution yet, so the
  # probe omits this datapoint (age = None). Treating that as breaching
  # would guarantee a false page at every exercise start. "No data because
  # the observer is down" is already covered by probe-silent/probe-errors;
  # this alarm speaks only to a genuinely stale successful run.
  treat_missing_data = "missing"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "freshness_gold_data" {
  count = var.pipeline_active ? 1 : 0

  alarm_name        = "cerberus-freshness-gold-data"
  alarm_description = "The newest object in the gold bucket is over ${var.gold_data_freshness_threshold_seconds}s old -- a healthy daily run refreshes the dbt marts and the current-state table."

  namespace   = "Cerberus/Pipeline"
  metric_name = "FreshnessSeconds"
  dimensions  = { Signal = "GoldData" }
  statistic   = "Maximum"

  period              = 3600
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = var.gold_data_freshness_threshold_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "missing"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
