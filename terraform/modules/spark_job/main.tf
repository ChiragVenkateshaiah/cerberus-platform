# 3.5: the service account cerberus-spark's driver/executor pods run as.
# The eks.amazonaws.com/role-arn annotation is what makes IRSA work -- EKS's
# built-in Pod Identity webhook injects AWS_ROLE_ARN/AWS_WEB_IDENTITY_TOKEN_FILE
# into any pod using this service account, which the S3A connector's
# WebIdentityTokenCredentialsProvider (set in the SparkApplication manifest,
# transform/spark/spark-application.yaml) reads to get temporary credentials
# scoped to exactly the cerberus-spark role -- never the broader node role.
#
# Just the identity, not the job run itself: the SparkApplication CR is a
# plain, manually-applied manifest (transform/spark/), not Terraform-managed
# -- submitting a job is a workload action, not infrastructure provisioning,
# the same distinction this project already draws between Terraform-managed
# IAM roles and the plain scripts that assume them (generate_payments.py,
# run_demo_query.sh).

resource "kubernetes_service_account" "spark" {
  metadata {
    name      = var.service_account_name
    namespace = var.namespace

    annotations = {
      "eks.amazonaws.com/role-arn" = var.role_arn
    }
  }
}
