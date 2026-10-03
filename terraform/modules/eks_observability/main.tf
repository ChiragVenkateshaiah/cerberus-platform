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
# - Grafana, reached only via `kubectl port-forward` (no Service exposure,
#   no ingress). AMP and read-only CloudWatch data sources; dashboards
#   provisioned from JSON committed under observability/grafana/dashboards/,
#   so they survive every teardown in git, as the metrics do in AMP.
#
# Applied only from envs/dev-compute, like iam_spark: both IRSA roles
# federate through the per-exercise cluster's OIDC provider, so they are
# lifecycle-coupled to the cluster, not to the standing roles.

locals {
  oidc_issuer_host = replace(var.eks_oidc_issuer_url, "https://", "")

  # Service account names are fixed (not chart-derived) because the IRSA
  # trust policies below pin them by name.
  prometheus_service_account = "prometheus-agent"
  grafana_service_account    = "grafana"

  dashboards_dir = "${path.module}/../../../observability/grafana/dashboards"
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

resource "aws_iam_role" "grafana" {
  name = "cerberus-grafana"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = var.eks_oidc_provider_arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_issuer_host}:sub" = "system:serviceaccount:${var.namespace}:${local.grafana_service_account}"
            "${local.oidc_issuer_host}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = {
    Phase     = "7"
    Component = "grafana"
  }
}

resource "aws_iam_role_policy" "grafana" {
  name = "cerberus-grafana-policy"
  role = aws_iam_role.grafana.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "QueryWorkspace"
        Effect = "Allow"
        Action = [
          "aps:QueryMetrics", "aps:GetSeries", "aps:GetLabels", "aps:GetMetricMetadata",
        ]
        Resource = var.amp_workspace_arn
      },
      {
        # Read-only CloudWatch, so one dashboard can show a run end to end
        # (Step Functions state next to the Spark panels). None of these
        # support resource-level scoping. ec2:DescribeRegions populates the
        # data source's region picker.
        Sid    = "ReadCloudWatchMetrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmsForMetric", "cloudwatch:DescribeAlarmHistory",
          "ec2:DescribeRegions",
        ]
        Resource = "*"
      }
    ]
  })
}

# --- Prometheus (agent mode) -------------------------------------------

locals {
  # Shared relabeling for both Spark jobs: driver pods only (Spark labels
  # them spark-role=driver), on the Spark UI port, which serves both the
  # PrometheusServlet sink and the executor summary endpoint.
  spark_driver_relabel = [
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

# --- Grafana ------------------------------------------------------------

resource "kubernetes_config_map" "dashboards" {
  metadata {
    name      = "grafana-dashboards-cerberus"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
  }

  data = {
    for f in fileset(local.dashboards_dir, "*.json") : f => file("${local.dashboards_dir}/${f}")
  }
}

resource "helm_release" "grafana" {
  name       = "grafana"
  repository = "https://grafana-community.github.io/helm-charts"
  chart      = "grafana"
  version    = var.grafana_chart_version
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  values = [yamlencode({
    serviceAccount = {
      name        = local.grafana_service_account
      annotations = { "eks.amazonaws.com/role-arn" = aws_iam_role.grafana.arn }
    }

    # ClusterIP only -- reached via kubectl port-forward (ADR 0016).
    service = { type = "ClusterIP" }

    plugins = ["grafana-amazonprometheus-datasource@${var.amp_plugin_version}"]

    datasources = {
      "datasources.yaml" = {
        apiVersion = 1
        datasources = [
          {
            name      = "Amazon Managed Prometheus"
            uid       = "amp"
            type      = "grafana-amazonprometheus-datasource"
            url       = var.amp_prometheus_endpoint
            access    = "proxy"
            isDefault = true
            jsonData = {
              httpMethod = "POST"
              sigV4Auth  = true
              # "default" = the AWS SDK's default credential chain, which
              # picks up the IRSA web-identity token on this pod.
              sigV4AuthType = "default"
              sigV4Region   = var.region
              sigv4Service  = "aps"
            }
          },
          {
            name   = "CloudWatch"
            uid    = "cloudwatch"
            type   = "cloudwatch"
            access = "proxy"
            jsonData = {
              authType      = "default"
              defaultRegion = var.region
            }
          },
        ]
      }
    }

    dashboardProviders = {
      "dashboardproviders.yaml" = {
        apiVersion = 1
        providers = [{
          name            = "cerberus"
          orgId           = 1
          folder          = "Cerberus"
          type            = "file"
          disableDeletion = true
          editable        = false
          options         = { path = "/var/lib/grafana/dashboards/cerberus" }
        }]
      }
    }
    # Mounted at /var/lib/grafana/dashboards/<key>, matching the provider.
    dashboardsConfigMaps = { cerberus = kubernetes_config_map.dashboards.metadata[0].name }

    # Nothing to persist: dashboards come from git, metrics from AMP.
    persistence   = { enabled = false }
    testFramework = { enabled = false }

    resources = {
      requests = { cpu = "100m", memory = "256Mi" }
      limits   = { memory = "512Mi" }
    }
  })]
}
