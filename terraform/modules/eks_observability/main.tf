# 7.7 (Phase 7 -- Prometheus for the EKS/Spark layer). The collection and
# viewing half of ADR 0016 (docs/adr/0016-prometheus-for-eks-spark.md);
# the storage half is the AMP workspace in envs/dev-standing
# (terraform/modules/prometheus_workspace), read here through
# terraform_remote_state.standing.
#
# - Prometheus in agent mode: scrapes, keeps only a WAL, remote_writes to
#   AMP. Scrape scope is bounded to the Spark driver and executors, the
#   Spark Operator's /metrics, kube-state-metrics and the node exporters.
#   The apiserver and raw cAdvisor jobs from the chart's default config are
#   deliberately absent, to keep series count near ADR 0016's ~10k estimate.
# - Viewing is the local Grafana (ADR 0022, ADR 0024); the in-cluster
#   Grafana was removed in ADR 0024 step 11.
#
# Applied only from envs/dev-compute, like iam_spark: the IRSA role
# federates through the per-exercise cluster's OIDC provider, so it is
# lifecycle-coupled to the cluster, not to the standing roles.

locals {
  oidc_issuer_host = replace(var.eks_oidc_issuer_url, "https://", "")

  # The service account name is fixed (not chart-derived) because the IRSA
  # trust policy below pins it by name.
  prometheus_service_account = "prometheus-agent"

  # 6c (ADR 0022 amendment): the Spark progress exporter. Its source stays
  # in git under observability/spark_progress and is mounted from a
  # ConfigMap, so there is no image to build or push.
  spark_progress_dir  = "${path.module}/../../../observability/spark_progress"
  spark_progress_name = "spark-progress-exporter"
  spark_progress_port = 9101
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.namespace
  }
}

# --- IRSA roles ---------------------------------------------------------
# Named cerberus-* because cerberus-admin's role management is scoped to
# that prefix (iam/cerberus-admin/policies, IamRoleMgmt).

resource "aws_iam_role" "prometheus" {
  name = "cerberus-prometheus"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = var.eks_oidc_provider_arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_issuer_host}:sub" = "system:serviceaccount:${var.namespace}:${local.prometheus_service_account}"
            "${local.oidc_issuer_host}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = {
    Phase     = "7"
    Component = "prometheus"
  }
}

resource "aws_iam_role_policy" "prometheus" {
  name = "cerberus-prometheus-policy"
  role = aws_iam_role.prometheus.id

  # Write-only, one workspace. The agent never queries AMP.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RemoteWriteToWorkspace"
        Effect   = "Allow"
        Action   = "aps:RemoteWrite"
        Resource = var.amp_workspace_arn
      }
    ]
  })
}

# --- Prometheus (agent mode) -------------------------------------------

locals {
  # Shared relabeling for both Spark jobs: driver pods only (Spark labels
  # them spark-role=driver), on the Spark UI port, which serves both the
  # PrometheusServlet sink and the executor summary endpoint.
  #
  # The phase rule keeps only Running pods. On 2026-10-13 the Completed
  # generator driver pod was still listed by pod discovery, and the silver
  # driver reused the generator driver's pod IP (commit aa9ec4a), so that
  # IP:4040 was scraped twice with both pods' labels (found in ADR 0022
  # step 5). UNVERIFIED until the 1M rehearsal shows one series per executor.
  spark_driver_relabel = [
    { source_labels = ["__meta_kubernetes_pod_phase"], regex = "Running", action = "keep" },
    { source_labels = ["__meta_kubernetes_pod_label_spark_role"], regex = "driver", action = "keep" },
    { source_labels = ["__meta_kubernetes_pod_container_port_number"], regex = "4040", action = "keep" },
    { source_labels = ["__meta_kubernetes_namespace"], target_label = "namespace" },
    { source_labels = ["__meta_kubernetes_pod_name"], target_label = "pod" },
    { source_labels = ["__meta_kubernetes_pod_label_sparkoperator_k8s_io_app_name"], target_label = "spark_app" },
  ]

  # Endpoint-role jobs for the two subcharts, matched by their service's
  # app.kubernetes.io/name label.
  subchart_relabel = {
    for name in ["kube-state-metrics", "prometheus-node-exporter"] : name => [
      { source_labels = ["__meta_kubernetes_service_label_app_kubernetes_io_name"], regex = name, action = "keep" },
      { source_labels = ["__meta_kubernetes_pod_node_name"], target_label = "node" },
    ]
  }

  scrape_configs = [
    {
      # The agent's own metrics -- prometheus_remote_storage_* is how the
      # pre-teardown WAL flush is checked.
      job_name       = "prometheus-agent"
      static_configs = [{ targets = ["localhost:9090"] }]
    },
    {
      job_name              = "spark-driver"
      metrics_path          = "/metrics/prometheus/"
      kubernetes_sd_configs = [{ role = "pod", namespaces = { names = [var.spark_jobs_namespace] } }]
      relabel_configs       = local.spark_driver_relabel
    },
    {
      job_name              = "spark-executors"
      metrics_path          = "/metrics/executors/prometheus/"
      kubernetes_sd_configs = [{ role = "pod", namespaces = { names = [var.spark_jobs_namespace] } }]
      relabel_configs       = local.spark_driver_relabel
    },
    {
      # 6c: Prometheus multi-target pattern. Each Running driver is
      # discovered as before, but the scrape goes to the exporter's /probe
      # with the driver's IP:4040 as ?target=. The exporter reads the
      # driver's status REST API and returns the cerberus_spark_* series.
      # instance is reset to the driver address so the series join with the
      # spark-driver job on namespace, pod and spark_app.
      job_name              = "spark-progress"
      metrics_path          = "/probe"
      scrape_timeout        = "10s"
      kubernetes_sd_configs = [{ role = "pod", namespaces = { names = [var.spark_jobs_namespace] } }]
      relabel_configs = concat(local.spark_driver_relabel, [
        { source_labels = ["__meta_kubernetes_pod_ip"], regex = "(.+)", replacement = "$1:4040", target_label = "__param_target" },
        { source_labels = ["__param_target"], target_label = "instance" },
        { target_label = "__address__", replacement = "${local.spark_progress_name}.${var.namespace}.svc:${local.spark_progress_port}" },
      ])
    },
    {
      # The operator chart annotates its controller pod with
      # prometheus.io/scrape and exposes /metrics on the "metrics" port.
      job_name              = "spark-operator"
      metrics_path          = "/metrics"
      kubernetes_sd_configs = [{ role = "pod", namespaces = { names = [var.spark_operator_namespace] } }]
      relabel_configs = [
        { source_labels = ["__meta_kubernetes_pod_annotation_prometheus_io_scrape"], regex = "true", action = "keep" },
        { source_labels = ["__meta_kubernetes_pod_container_port_name"], regex = "metrics", action = "keep" },
        { source_labels = ["__meta_kubernetes_pod_name"], target_label = "pod" },
      ]
    },
    {
      job_name              = "kube-state-metrics"
      kubernetes_sd_configs = [{ role = "endpoints", namespaces = { names = [var.namespace] } }]
      relabel_configs       = local.subchart_relabel["kube-state-metrics"]
    },
    {
      job_name              = "node-exporter"
      kubernetes_sd_configs = [{ role = "endpoints", namespaces = { names = [var.namespace] } }]
      relabel_configs       = local.subchart_relabel["prometheus-node-exporter"]
    },
  ]
}

resource "helm_release" "prometheus" {
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "prometheus"
  version    = var.prometheus_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [yamlencode({
    serviceAccounts = {
      server = {
        name        = local.prometheus_service_account
        annotations = { "eks.amazonaws.com/role-arn" = aws_iam_role.prometheus.arn }
      }
    }

    server = {
      # Agent mode. Replaces the chart's default args entirely, because
      # several of them (--storage.tsdb.*, --web.console.*) are server-mode
      # only and Prometheus refuses to start with them alongside --agent.
      # Prometheus 3 spells it --agent; --enable-feature=agent is the
      # removed v2 form. Verified against `prometheus --help` for v3.15.0.
      defaultFlagsOverride = [
        "--agent",
        "--config.file=/etc/config/prometheus.yml",
        "--storage.agent.path=/data",
        "--web.enable-lifecycle",
      ]

      # The WAL only buffers until remote_write ships it. emptyDir is
      # enough: losing it on a pod restart loses at most the unsent tail.
      persistentVolume = { enabled = false }

      global = {
        scrape_interval     = var.scrape_interval
        evaluation_interval = var.scrape_interval
        external_labels     = { cluster = var.cluster_name }
      }

      resources = {
        requests = { cpu = "100m", memory = "256Mi" }
        limits   = { memory = "512Mi" }
      }
    }

    # Rule evaluation, alerting and pushes are all out of scope (agent
    # mode can't evaluate rules anyway; ADR 0016 leaves the Pushgateway
    # as a follow-up).
    alertmanager             = { enabled = false }
    "prometheus-pushgateway" = { enabled = false }

    # kube-state-metrics (subchart 8.6.0 in prometheus 29.35.0) drops node
    # labels by default. Allow the capacity type so kube_node_labels carries
    # label_eks_amazonaws_com_capacity_type (kube-state-metrics snake_cases
    # label names), for Spot vs on-demand node counts on the run dashboard
    # (ADR 0022). The chart joins this list with commas into
    # --metric-labels-allowlist.
    "kube-state-metrics" = {
      metricLabelsAllowlist = ["nodes=[eks.amazonaws.com/capacityType]"]
    }

    # The chart injects its default jobs (apiserver, nodes, cAdvisor, every
    # annotated pod/service, ...) from this separate map, *in addition to*
    # serverFiles' scrape_configs below. null removes the whole map, so the
    # bounded list below is the only one -- caught by rendering the chart
    # before the first apply.
    scrapeConfigs = null

    serverFiles = {
      "prometheus.yml" = {
        # null removes the chart default's rule_files list -- agent mode
        # rejects a config that has one.
        rule_files     = null
        scrape_configs = local.scrape_configs
        # remote_write lives here rather than in server.remoteWrite on
        # purpose. The chart's ConfigMap template pulls scrape_configs out
        # of this map and then toYaml's whatever is left; with rule_files
        # gone, an empty remainder renders as a stray `{}` line and
        # invalid YAML (caught by `promtool check config --agent` on the
        # rendered chart). Keeping remote_write here makes it that
        # remainder.
        remote_write = [{
          url   = var.amp_remote_write_url
          sigv4 = { region = var.region }
        }]
      }
    }
  })]
}

# --- Spark progress exporter (6c) ----------------------------------------
# Reads each Spark driver's status REST API and serves a few cerberus_spark_*
# series (rows made, rows read, rows added, current activity) for the story
# dashboard. Stdlib Python on the Spark image already pulled on the nodes.
# UNVERIFIED on EKS until the 1M rehearsal: the file passes pytest against
# fixtures from a local Spark run only.

resource "kubernetes_config_map" "spark_progress" {
  metadata {
    name      = local.spark_progress_name
    namespace = kubernetes_namespace.monitoring.metadata[0].name
  }

  data = {
    "exporter.py" = file("${local.spark_progress_dir}/exporter.py")
  }
}

resource "kubernetes_deployment_v1" "spark_progress" {
  metadata {
    name      = local.spark_progress_name
    namespace = kubernetes_namespace.monitoring.metadata[0].name
    labels    = { app = local.spark_progress_name }
  }

  spec {
    replicas = 1

    selector {
      match_labels = { app = local.spark_progress_name }
    }

    template {
      metadata {
        labels = { app = local.spark_progress_name }
        # Roll the pod when the script changes (a ConfigMap edit alone does
        # not restart it).
        annotations = {
          "cerberus/exporter-sha256" = filesha256("${local.spark_progress_dir}/exporter.py")
        }
      }

      spec {
        automount_service_account_token = false

        security_context {
          run_as_non_root = true
          run_as_user     = 185 # the spark user in apache/spark
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name    = "exporter"
          image   = var.spark_progress_image
          command = ["python3", "/app/exporter.py", tostring(local.spark_progress_port)]

          env {
            name  = "PYTHONDONTWRITEBYTECODE"
            value = "1"
          }

          port {
            name           = "http"
            container_port = local.spark_progress_port
          }

          readiness_probe {
            http_get {
              path = "/healthz"
              port = "http"
            }
            period_seconds = 10
          }

          resources {
            requests = { cpu = "10m", memory = "32Mi" }
            limits   = { memory = "64Mi" }
          }

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          volume_mount {
            name       = "app"
            mount_path = "/app"
            read_only  = true
          }
        }

        volume {
          name = "app"
          config_map {
            name = kubernetes_config_map.spark_progress.metadata[0].name
          }
        }
      }
    }
  }

  timeouts {
    create = "5m"
  }
}

resource "kubernetes_service_v1" "spark_progress" {
  metadata {
    name      = local.spark_progress_name
    namespace = kubernetes_namespace.monitoring.metadata[0].name
  }

  spec {
    type     = "ClusterIP"
    selector = { app = local.spark_progress_name }

    port {
      name        = "http"
      port        = local.spark_progress_port
      target_port = "http"
    }
  }
}
