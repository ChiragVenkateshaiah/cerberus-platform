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

resource "aws_iam_role_policy" "ci_plan" {
  name = "cerberus-ci-plan-policy"
  role = aws_iam_role.ci_plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadTerraformState"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          var.tfstate_bucket_arn,
          "${var.tfstate_bucket_arn}/*",
        ]
      },
      {
        Sid      = "StateLock"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = var.tfstate_lock_table_arn
      },
      {
        Sid    = "ReadOnlyPlatform"
        Effect = "Allow"
        Action = [
          "s3:GetBucket*", "s3:GetObject", "s3:GetLifecycleConfiguration", "s3:GetEncryptionConfiguration",
          "s3:ListBucket", "s3:ListAllMyBuckets", "s3:GetAccountPublicAccessBlock", "s3:GetBucketPublicAccessBlock",
          "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
          "glue:GetDatabase*", "glue:GetTable*", "glue:GetPartition*",
          "athena:GetWorkGroup", "athena:ListWorkGroups",
          "lambda:GetFunction*", "lambda:ListVersionsByFunction", "lambda:GetLayerVersion",
          "ecs:Describe*", "ecs:List*",
          "ecr:Describe*", "ecr:GetRepositoryPolicy", "ecr:ListTagsForResource",
          "states:Describe*", "states:List*",
          "scheduler:Get*", "scheduler:List*",
          "events:Describe*", "events:List*",
          "logs:Describe*", "logs:ListTagsForResource", "logs:GetLogGroupFields",
          "ec2:Describe*",
          "xray:Get*",
          "sts:GetCallerIdentity",
        ]
        Resource = "*"
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
        Sid      = "ManageMedallionBuckets"
        Effect   = "Allow"
        Action   = "s3:*"
        Resource = [for arn in var.bucket_arns : arn]
      },
      {
        Sid      = "ManageMedallionBucketContents"
        Effect   = "Allow"
        Action   = "s3:*"
        Resource = [for arn in var.bucket_arns : "${arn}/*"]
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
        Sid      = "ManageAthena"
        Effect   = "Allow"
        Action   = "athena:*"
        Resource = "arn:aws:athena:${var.region}:${var.account_id}:workgroup/cerberus-platform*"
      },
      {
        Sid      = "ManageIngestionLambda"
        Effect   = "Allow"
        Action   = "lambda:*"
        Resource = "arn:aws:lambda:${var.region}:${var.account_id}:function:cerberus-ingest-*"
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
        Sid      = "ManageLogGroups"
        Effect   = "Allow"
        Action   = "logs:*"
        Resource = "arn:aws:logs:${var.region}:${var.account_id}:log-group:/cerberus/*"
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
      }
    ]
  })
}
