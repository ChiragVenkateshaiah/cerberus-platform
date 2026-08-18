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

# Kubernetes RBAC, not IAM/IRSA: the Spark-on-Kubernetes scheduler backend
# (running inside the driver, under this service account) needs to GET its
# own driver pod and create/watch/delete executor pods directly against the
# Kubernetes API -- discovered live via a real submission failure
# ("cannot get resource pods ... forbidden") once IRSA's S3-only grant
# turned out not to cover this at all. configmaps are included because the
# scheduler also uses them for executor pod spec templating in some Spark
# versions; services is the third resource the upstream Spark-on-K8s docs'
# reference RBAC example grants alongside pods.
resource "kubernetes_role" "spark_driver" {
  metadata {
    name      = "${var.service_account_name}-driver"
    namespace = var.namespace
  }

  rule {
    api_groups = [""]
    # persistentvolumeclaims added alongside configmaps -- same
    # deletecollection-by-label-selector cleanup pattern, discovered live
    # in the same run (shuffle/local-storage PVC cleanup after the
    # configmap fix already applied). Matches the 4 resources the upstream
    # Spark-on-Kubernetes docs' reference RBAC grants.
    resources = ["pods", "services", "configmaps", "persistentvolumeclaims"]
    # deletecollection is separate from delete -- discovered live: post-job
    # cleanup deletes executor configmaps/PVCs by label selector
    # (DELETE .../<resource>?labelSelector=...), which Kubernetes routes
    # through deletecollection, not delete. Non-fatal (job still completed),
    # but would hit the same Forbidden on every run without it.
    verbs = ["get", "list", "watch", "create", "delete", "deletecollection"]
  }
}

resource "kubernetes_role_binding" "spark_driver" {
  metadata {
    name      = "${var.service_account_name}-driver"
    namespace = var.namespace
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.spark_driver.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.spark.metadata[0].name
    namespace = var.namespace
  }
}
