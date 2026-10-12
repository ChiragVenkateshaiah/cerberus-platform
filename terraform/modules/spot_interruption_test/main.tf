# 8.8 step 4: a Spot interruption test. An AWS FIS experiment template that
# sends the real Spot signals to ONE running instance of the executor node
# group: an EC2 rebalance recommendation at once, then the 2-minute
# interruption notice, then the termination.
#
# What the test exercises, end to end (all already in place):
#   - EKS managed node group (Spot, Capacity Rebalancing on): launches a
#     replacement node, then cordons and drains the interrupted one;
#   - the drain evicts the executor pods, whose preStop hook (/opt/decom.sh)
#     starts Spark's executor decommissioning, with shuffle and RDD block
#     migration (transform/spark/spark-application.yaml, #94);
#   - dynamic allocation asks for executors again; Cluster Autoscaler and
#     the Auto Scaling group's minimum bring nodes back.
# The driver is on the On-Demand system node, out of the target's reach.
#
# Applied only from envs/dev-compute: the template targets a tag on
# instances that exist only during an exercise, and goes with the cluster.
# A template costs nothing; FIS bills per action-minute when an experiment
# runs (about $0.10/min, a few minutes per test).

data "aws_caller_identity" "current" {}

locals {
  target_tag_key = "eks:nodegroup-name"
}

# Named cerberus-* because cerberus-admin's role management and PassRole are
# scoped to that prefix (iam/cerberus-admin/policies).
resource "aws_iam_role" "fis" {
  name = "cerberus-fis-spot-interruption"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "fis.amazonaws.com" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        }
      }
    ]
  })

  tags = {
    Phase     = "8"
    Component = "spot-interruption-test"
  }
}

# The action's two documented permissions. The interruption is limited to
# the executor group's instances by the tag EKS puts on them, so a template
# edited by mistake still can't reach the system node.
resource "aws_iam_role_policy" "fis" {
  name = "cerberus-fis-spot-interruption-policy"
  role = aws_iam_role.fis.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InterruptExecutorSpotNodes"
        Effect   = "Allow"
        Action   = "ec2:SendSpotInstanceInterruptions"
        Resource = "arn:aws:ec2:*:${data.aws_caller_identity.current.account_id}:instance/*"
        Condition = {
          StringEquals = { "ec2:ResourceTag/${local.target_tag_key}" = var.executor_node_group_name }
        }
      },
      {
        Sid      = "DescribeTargets"
        Effect   = "Allow"
        Action   = "ec2:DescribeInstances"
        Resource = "*"
      }
    ]
  })
}

resource "aws_fis_experiment_template" "spot_interruption" {
  description = "8.8: interrupt one Spot executor node of ${var.cluster_name} during the silver job"
  role_arn    = aws_iam_role.fis.arn

  # Started by hand (exercise.sh --interrupt-spot) and over in minutes; the
  # experiment's own end is the stop.
  stop_condition {
    source = "none"
  }

  action {
    name      = "interrupt-one-executor-node"
    action_id = "aws:ec2:send-spot-instance-interruptions"

    parameter {
      key   = "durationBeforeInterruption"
      value = var.duration_before_interruption
    }

    target {
      key   = "SpotInstances"
      value = "executor-node"
    }
  }

  target {
    name           = "executor-node"
    resource_type  = "aws:ec2:spot-instance"
    selection_mode = "COUNT(1)"

    resource_tag {
      key   = local.target_tag_key
      value = var.executor_node_group_name
    }

    filter {
      path   = "State.Name"
      values = ["running"]
    }
  }

  tags = {
    Name      = "cerberus-spot-interruption"
    Phase     = "8"
    Component = "spot-interruption-test"
  }

  depends_on = [aws_iam_role_policy.fis]
}
