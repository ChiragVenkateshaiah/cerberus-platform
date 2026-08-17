# 3.4: installs kubeflow/spark-operator (the actively maintained successor
# to the archived GoogleCloudPlatform/spark-on-k8s-operator) onto the EKS
# cluster built in 3.2. Two namespaces, not one: the operator's own
# controller/webhook, and a separate jobs namespace it's configured to
# watch -- the chart's own default (spark.jobNamespaces = ["default"]) is
# deliberately not used, so 3.5's SparkApplication and its IRSA-bound
# service account don't land in the cluster's default namespace.

resource "kubernetes_namespace" "operator" {
  metadata {
    name = var.operator_namespace
  }
}

resource "kubernetes_namespace" "jobs" {
  metadata {
    name = var.jobs_namespace
  }
}

resource "helm_release" "spark_operator" {
  name       = "spark-operator"
  repository = "https://kubeflow.github.io/spark-operator"
  chart      = "spark-operator"
  namespace  = kubernetes_namespace.operator.metadata[0].name
  version    = var.chart_version

  set {
    name  = "spark.jobNamespaces[0]"
    value = kubernetes_namespace.jobs.metadata[0].name
  }
}
