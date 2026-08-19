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

# --- Access + RBAC for the orchestration transform task (4.2) --------------
# A different principal than the two resources above: not the Spark
# driver's own service account, but the ECS task
# (cerberus-orchestration-transform) that submits and polls the
# SparkApplication in the first place -- the containerized adaptation of
# what submit_job.sh already does by hand. The access entry lives here,
# not in the eks module where every other cluster-level access concern
# lives -- see eks/main.tf's NB comment: eks already feeds module.iam's
# cerberus-spark trust policy, so an access entry needing module.iam's
# orchestration_transform role ARN would have made eks depend back on iam,
# a real module cycle. This module already depends on both with no
# reverse edge, and it's the natural home anyway -- the entry and the RBAC
# that actually grants this principal's permissions belong together.
#
# Deliberately narrow, same choice 3.4/3.5 already made for the driver's
# own service account: type STANDARD, no AWS-managed access-policy
# association -- just a Kubernetes group mapping, with the actual
# permissions coming from the plain RBAC role/binding below rather than a
# broader Amazon-managed EKS access policy.

resource "aws_eks_access_entry" "orchestration_transform" {
  cluster_name      = var.cluster_name
  principal_arn     = var.orchestration_transform_role_arn
  kubernetes_groups = [var.orchestration_transform_kubernetes_group]
  type              = "STANDARD"
}

# Scoped to exactly what submit_job.sh's containerized adaptation does:
# create/get/delete/watch the SparkApplication itself, plus read pod state
# and logs for its own polling and on-failure-log-dump steps -- no write
# access to pods/configmaps/PVCs the way the driver's own role above needs
# (this principal never runs Spark code, it only submits and watches).

resource "kubernetes_role" "orchestration_transform" {
  metadata {
    name      = "cerberus-orchestration-transform"
    namespace = var.namespace
  }

  rule {
    api_groups = ["sparkoperator.k8s.io"]
    resources  = ["sparkapplications"]
    verbs      = ["get", "list", "watch", "create", "delete"]
  }

  rule {
    api_groups = [""]
    resources  = ["pods"]
    verbs      = ["get", "list", "watch"]
  }

  rule {
    api_groups = [""]
    resources  = ["pods/log"]
    verbs      = ["get"]
  }
}

resource "kubernetes_role_binding" "orchestration_transform" {
  metadata {
    name      = "cerberus-orchestration-transform"
    namespace = var.namespace
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.orchestration_transform.metadata[0].name
  }

  subject {
    kind      = "Group"
    name      = var.orchestration_transform_kubernetes_group
    api_group = "rbac.authorization.k8s.io"
  }
}
