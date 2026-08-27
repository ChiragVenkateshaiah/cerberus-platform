# ADR 0011 (5.1): GitHub Actions authenticates to AWS via OIDC federation,
# never long-lived access keys -- the same "no static credentials, ever"
# discipline every other identity in this project has held since 1.6 (every
# role assumed via STS, IRSA, or a service principal, never an IAM user's
# keys).
#
# Two roles, not one, because this repo is PUBLIC:
#   - cerberus-ci-plan: trusted for ANY workflow run in this repo (any
#     branch, any pull_request), because `terraform plan` has to run
#     against every PR to be useful as a PR check. Its policy is read-only
#     across every service this stack touches -- a fork's PR (gated by
#     GitHub's own "require approval for first-time contributors" default,
#     but not relying on that alone) can therefore never do more than read
#     already-public-shaped infrastructure metadata.
#   - cerberus-ci-apply: trusted ONLY for `refs/heads/main` -- a token with
#     this role's `sub` claim can only be minted by a workflow run whose
#     ref is main, which for this repo only happens on a direct push/merge
#     to main (something only a repo collaborator can do). This role alone
#     carries create/update/delete permissions.
# The real scoping is done on the token's dedicated `repository`/`ref`
# claims, not `sub` substring patterns -- discovered live (2026-08-21) that
# this account's GitHub org embeds immutable numeric IDs into `sub`
# (`repo:OWNER@12345/REPO@67890:pull_request`, not the plain
# `repo:OWNER/REPO:...` AWS's own docs still show), which broke a
# StringLike("repo:${slug}:*") condition outright -- confirmed via
# CloudTrail's actual rejected AssumeRoleWithWebIdentity events, not
# inferred from docs. `repository`/`ref` are separate top-level claims
# GitHub's token always includes, immune to whatever format `sub` happens
# to use. Both always name the *base* repository/ref a workflow ran in --
# never a fork's -- so matching them doesn't by itself exclude
# fork-originated tokens (a fork's PR run is still executed against the
# base repo's context); the `ref` restriction on cerberus-ci-apply is what
# actually separates "any PR in this repo can plan" from "only a push to
# main can apply."
#
# A loose `sub` StringLike is also required -- not for scoping, AWS's own
# IAM API rejects any GitHub-OIDC trust policy that doesn't evaluate `sub`
# or `job_workflow_ref` at all, regardless of what other conditions are
# present (MalformedPolicyDocument, discovered live on the first apply
# attempt after the fix above). `repo:${github_owner}*` satisfies that
# requirement without doing any of the real access control -- `repository`
# and (for apply) `ref` are the conditions that actually matter, combined
# with AND semantics against this same Condition block.

data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

locals {
  repo_slug = "${var.github_owner}/${var.github_repo}"
}

resource "aws_iam_role" "ci_plan" {
  name = "cerberus-ci-plan"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud"        = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:repository" = local.repo_slug
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_owner}*"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role" "ci_apply" {
  name = "cerberus-ci-apply"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud"        = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:repository" = local.repo_slug
            "token.actions.githubusercontent.com:ref"        = "refs/heads/main"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_owner}*"
          }
        }
      }
    ]
  })
}

# --- cerberus-ci-plan: read-only across every service envs/dev-standing --
# manages, plus the Terraform state bucket/lock table (plan still reads
# state and takes/releases the DynamoDB lock even though it writes nothing
# to AWS resources themselves).
#
# Read access itself is AWS's managed ReadOnlyAccess, not a hand-enumerated
# action list -- discovered live (2026-08-21) that a hand-picked list is
# genuinely impractical here: a single aws_s3_bucket resource's refresh
# alone calls a dozen-plus distinct Get* actions (GetAccelerateConfiguration
# was the one that broke first), and the same is true of IAM/Glue/ECS
# resources. Attaching the managed policy is the third deliberate exception
# to this project's inline-only-policy convention (alongside
# AWSLambdaBasicExecutionRole and AmazonECSTaskExecutionRolePolicy in
# terraform/modules/iam) -- broad, standard, AWS-defined *read* capability,
# not a project-specific data-plane grant, and it contains zero
# write/create/delete actions, so the property that actually matters (this
# role can never mutate anything) holds structurally, not by convention.
resource "aws_iam_role_policy_attachment" "ci_plan_read_only" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "ci_plan" {
  name = "cerberus-ci-plan-policy"
  role = aws_iam_role.ci_plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # ReadOnlyAccess already covers s3:GetObject/ListBucket broadly;
        # kept explicit anyway for self-documentation, matching this
        # project's preference for stating intent rather than relying on a
        # managed policy's coverage implicitly.
        Sid    = "ReadTerraformState"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          var.tfstate_bucket_arn,
          "${var.tfstate_bucket_arn}/*",
        ]
      },
      {
        # Not covered by ReadOnlyAccess -- acquiring/releasing the
        # DynamoDB lock during `terraform plan` needs Put/Delete on the
        # lock item, which are write actions ReadOnlyAccess deliberately
        # excludes even though no real infrastructure is being mutated.
        Sid      = "StateLock"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = var.tfstate_lock_table_arn
      }
    ]
  })
}

# --- cerberus-ci-apply: full create/update/delete on envs/dev-standing's --
# own resources, name-prefix-scoped wherever the service supports it (most
# importantly IAM -- this role can manage cerberus-* roles/policies only,
# never itself, never cerberus-admin, never the compute-side cerberus-spark
# role -- the same privilege-escalation guard 7.3's eventual least-privilege
# review will hold every role in this project to).

resource "aws_iam_role_policy" "ci_apply" {
  name = "cerberus-ci-apply-policy"
  role = aws_iam_role.ci_apply.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "TerraformState"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [var.tfstate_bucket_arn, "${var.tfstate_bucket_arn}/*"]
      },
      {
        Sid      = "StateLock"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = var.tfstate_lock_table_arn
      },
      {
        # Includes the Athena results bucket alongside bronze/silver/gold --
        # a separate bucket the athena module owns, missing entirely from
        # the first live apply attempt (2026-08-21): its ownership controls
        # and lifecycle config refresh both 403'd.
        Sid      = "ManageMedallionBuckets"
        Effect   = "Allow"
        Action   = "s3:*"
        Resource = concat([for arn in var.bucket_arns : arn], [var.athena_results_bucket_arn])
      },
      {
        Sid      = "ManageMedallionBucketContents"
        Effect   = "Allow"
        Action   = "s3:*"
        Resource = concat([for arn in var.bucket_arns : "${arn}/*"], ["${var.athena_results_bucket_arn}/*"])
      },
      {
        # Name-prefix-scoped: this role can only ever touch roles/policies
        # named cerberus-ingestion*/cerberus-transform*/cerberus-serving*/
        # cerberus-orchestration-* -- the standing roles envs/dev-standing's
        # own iam module manages. It can never modify cerberus-admin,
        # cerberus-spark (compute-side), or its own cerberus-ci-* roles --
        # no path to self-escalation.
        Sid    = "ManageStandingIamRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole", "iam:TagRole", "iam:UntagRole",
          "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole", "iam:PassRole",
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:role/cerberus-ingestion*",
          "arn:aws:iam::${var.account_id}:role/cerberus-transform",
          "arn:aws:iam::${var.account_id}:role/cerberus-serving",
          "arn:aws:iam::${var.account_id}:role/cerberus-orchestration-*",
          # EventBridge Scheduler's own execution role (module.step_functions
          # .aws_iam_role.scheduler) -- doesn't match any of the patterns
          # above, missed originally (iam:GetRole 403'd on the first live
          # apply).
          "arn:aws:iam::${var.account_id}:role/cerberus-ingest-payments-scheduler",
          # 6.1: the data-freshness probe's own execution role and its
          # EventBridge Scheduler role (terraform/modules/observability) --
          # cerberus-freshness-probe and cerberus-freshness-probe-scheduler,
          # neither matching the patterns above. Covers iam:PassRole too
          # (Lambda + Scheduler both need the probe roles passed to them).
          "arn:aws:iam::${var.account_id}:role/cerberus-freshness-probe*",
        ]
      },
      {
        Sid    = "ManageGlueCatalog"
        Effect = "Allow"
        Action = "glue:*"
        Resource = [
          "arn:aws:glue:${var.region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.region}:${var.account_id}:database/cerberus_platform",
          "arn:aws:glue:${var.region}:${var.account_id}:table/cerberus_platform/*",
        ]
      },
      {
        # The workgroup's real name is `cerberus_platform` (underscore) --
        # `aws_athena_workgroup.this.name` in terraform/modules/athena. The
        # original hyphenated pattern here never matched it, which is why
        # the first live apply 403'd on athena:GetWorkGroup.
        Sid      = "ManageAthena"
        Effect   = "Allow"
        Action   = "athena:*"
        Resource = "arn:aws:athena:${var.region}:${var.account_id}:workgroup/cerberus_platform"
      },
      {
        Sid    = "ManageStandingLambdas"
        Effect = "Allow"
        Action = "lambda:*"
        Resource = [
          "arn:aws:lambda:${var.region}:${var.account_id}:function:cerberus-ingest-*",
          # The Faker layer 1.3's Lambda depends on -- a separate ARN
          # namespace from the function itself, missed originally
          # (lambda:GetLayerVersion 403'd on the first live apply).
          "arn:aws:lambda:${var.region}:${var.account_id}:layer:cerberus-ingestion-*",
          # 6.1: the data-freshness probe Lambda
          # (terraform/modules/observability) -- boto3-only, no layer.
          "arn:aws:lambda:${var.region}:${var.account_id}:function:cerberus-freshness-probe*",
        ]
      },
      {
        Sid      = "ManageOrchestrationEcs"
        Effect   = "Allow"
        Action   = "ecs:*"
        Resource = "arn:aws:ecs:${var.region}:${var.account_id}:*/cerberus-*"
      },
      {
        Sid      = "ManageOrchestrationEcr"
        Effect   = "Allow"
        Action   = "ecr:*"
        Resource = "arn:aws:ecr:${var.region}:${var.account_id}:repository/cerberus-*"
      },
      {
        Sid      = "ManageStepFunctions"
        Effect   = "Allow"
        Action   = "states:*"
        Resource = "arn:aws:states:${var.region}:${var.account_id}:stateMachine:cerberus-*"
      },
      {
        Sid      = "ManageEventBridgeScheduler"
        Effect   = "Allow"
        Action   = "scheduler:*"
        Resource = "arn:aws:scheduler:${var.region}:${var.account_id}:schedule/*/cerberus-*"
      },
      {
        # 6.1: the pipeline observability dashboard
        # (terraform/modules/observability). PutDashboard/GetDashboard/
        # DeleteDashboards support resource-level scoping to the dashboard
        # ARN -- CloudWatch dashboard ARNs carry an empty region segment
        # (arn:aws:cloudwatch::ACCOUNT:dashboard/NAME). ListDashboards
        # isn't needed: the AWS provider reads a dashboard by GetDashboard,
        # not by listing.
        Sid      = "ManageObservabilityDashboard"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutDashboard", "cloudwatch:GetDashboard", "cloudwatch:DeleteDashboards"]
        Resource = "arn:aws:cloudwatch::${var.account_id}:dashboard/cerberus-platform-pipeline"
      },
      {
        # Missing entirely from the first live apply -- ec2:DescribeVpcs
        # 403'd immediately, the first resource module.vpc's refresh
        # touches. envs/dev-standing's trimmed vpc module (VPC, subnets,
        # IGW, route tables, the S3 gateway endpoint -- no NAT/EIP, those
        # live in dev-compute's vpc_nat) needs EC2 access this project
        # never granted anywhere before, since every prior EKS/VPC apply
        # (Phase 3/4) ran as cerberus-admin by hand, never through a scoped
        # CI role.
        #
        # Split into two statements, not one blanket ec2:* on "*": the
        # mutating actions (Create/Delete/Modify/Attach/Associate) DO
        # support EC2's resource-type ARN format, so they're scoped to
        # exactly the 5 resource types this module creates -- the same
        # name-prefix-scoping discipline as IAM/Glue/Lambda above, just
        # expressed as a resource *type* wildcard since EC2 IDs aren't
        # predictable before creation. The Describe* actions in the second
        # statement structurally cannot be scoped this way -- EC2's action
        # matrix requires Resource "*" for them regardless of policy
        # design, which is why they're pulled into a statement of their
        # own instead of forcing a single Resource shape on both groups.
        Sid    = "ManageVpcCore"
        Effect = "Allow"
        Action = "ec2:*"
        Resource = [
          "arn:aws:ec2:${var.region}:${var.account_id}:vpc/*",
          "arn:aws:ec2:${var.region}:${var.account_id}:subnet/*",
          "arn:aws:ec2:${var.region}:${var.account_id}:route-table/*",
          "arn:aws:ec2:${var.region}:${var.account_id}:internet-gateway/*",
          "arn:aws:ec2:${var.region}:${var.account_id}:vpc-endpoint/*",
        ]
      },
      {
        # DescribeSecurityGroups and DescribePrefixLists added after a
        # second live apply attempt (2026-08-23) got past the first six
        # gaps cleanly and 403'd on these two instead --
        # orchestration_runner's security group and the S3 gateway
        # endpoint's AWS-managed prefix list, neither reachable by any of
        # the resource-type-scoped actions above (security groups and
        # prefix lists aren't among ManageVpcCore's 5 resource types, and
        # like the other Describe* actions here, EC2 requires Resource "*"
        # for both regardless).
        Sid    = "DescribeVpcCore"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeRouteTables",
          "ec2:DescribeInternetGateways", "ec2:DescribeVpcEndpoints", "ec2:DescribeTags",
          "ec2:DescribeSecurityGroups", "ec2:DescribePrefixLists",
        ]
        Resource = "*"
      },
      {
        # `/cerberus/*` never matched any real log group this project
        # creates -- orchestration_runner's two ECS task log groups live
        # under `/ecs/cerberus-orchestration-*` and step_functions' own
        # under `/aws/vendedlogs/states/cerberus-platform-orchestration*`,
        # AWS-conventional prefixes, not a project-chosen one. The original
        # pattern was a guess that was never verified against the actual
        # resources (logs:ListTagsForResource 403'd on all three on the
        # first live apply).
        Sid    = "ManageLogGroups"
        Effect = "Allow"
        Action = "logs:*"
        Resource = [
          "arn:aws:logs:${var.region}:${var.account_id}:log-group:/ecs/cerberus-orchestration-*",
          "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/vendedlogs/states/cerberus-platform-orchestration*",
          # 6.1: the freshness probe's explicit aws_cloudwatch_log_group
          # (terraform/modules/observability). The ingestion Lambda has no
          # explicit log group, so /aws/lambda/* was never needed here
          # before.
          "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/lambda/cerberus-freshness-probe*",
        ]
      },
      {
        # ECR repos, task definitions, and CloudWatch Logs resource
        # policies are frequently account/region-scoped rather than
        # resource-ARN-scoped for their read-side Describe/List calls --
        # granted broadly here since they're inherently read-only
        # discovery operations, not mutations.
        Sid    = "DiscoveryReads"
        Effect = "Allow"
        Action = [
          "ecs:DescribeClusters", "ecs:ListClusters", "ecs:DescribeTaskDefinition",
          "ecr:DescribeRepositories", "ecr:GetAuthorizationToken",
          "logs:DescribeLogGroups",
          "sts:GetCallerIdentity",
        ]
        Resource = "*"
      },
      {
        # Read-only, deliberately -- module.github_oidc's own resources
        # (the OIDC provider and both CI roles) live in this same state, so
        # a whole-root `terraform apply` has to be able to refresh them
        # even though this role never modifies them. No Put*/Update*/
        # Create*/Delete* action appears here: this role cannot rewrite its
        # own trust policy, cerberus-ci-plan's, or the OIDC provider's --
        # any real change to module.github_oidc requires a human running
        # `terraform apply` as cerberus-admin, the same self-escalation
        # guard ManageStandingIamRoles's resource scoping already holds
        # every other role in this project to.
        Sid    = "ReadOwnCiIdentity"
        Effect = "Allow"
        Action = [
          "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListRoleTags",
          "iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviderTags",
        ]
        Resource = [
          aws_iam_role.ci_plan.arn,
          aws_iam_role.ci_apply.arn,
          aws_iam_openid_connect_provider.github_actions.arn,
        ]
      }
    ]
  })
}
