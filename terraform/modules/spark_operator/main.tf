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

# 8.6: pull the Spark image onto every node while dev-compute is created,
# so the driver and executors don't each pull it at run time. The timed
# exercise of 2026-10-08 (exercise-20261008T160759Z) spent ~10 s on the
# driver's pull and most of the executors' 19 s schedule + pull + start
# inside RunTransform. Both manifests in transform/spark/ use
# imagePullPolicy: IfNotPresent, so a cached image is used as-is.
#
# The container runs the Spark image itself with `sleep infinity` rather
# than an init container plus a pause image: one image to pull, not two,
# and it stays resident so the kubelet's image GC won't evict the image
# it's protecting. In the operator namespace, not the jobs one: the jobs
# namespace is scraped for Spark metrics and counted by Grafana's pod-phase
# panel, while the operator namespace's scrape keeps only annotated pods.
# Apply does NOT wait for the pull: on exercise-20261009T062108Z the
# DaemonSet reported "Creation complete after 1s" and the image arrived in
# the background while the Prometheus/Grafana charts installed -- still
# well before the execution started (both pods logged "already present
# on machine", RunTransform 178.3 -> 159.0 s). A run started right after
# an apply could still pull for itself: slower, not a failure.
resource "kubernetes_daemon_set_v1" "spark_image_prepull" {
  metadata {
    name      = "spark-image-prepull"
    namespace = kubernetes_namespace.operator.metadata[0].name
  }

  spec {
    selector {
      match_labels = { app = "spark-image-prepull" }
    }

    template {
      metadata {
        labels = { app = "spark-image-prepull" }
      }

      spec {
        container {
          name              = "spark-image"
          image             = var.spark_image
          image_pull_policy = "IfNotPresent"
          command           = ["sleep", "infinity"]

          resources {
            requests = { cpu = "1m", memory = "8Mi" }
            limits   = { cpu = "10m", memory = "16Mi" }
          }
        }

        termination_grace_period_seconds = 0
      }
    }
  }

  timeouts {
    create = "10m"
  }
}
