output "eks_cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "spark_jobs_namespace" {
  description = "Kubernetes namespace the Spark Operator watches for SparkApplication resources -- where 3.5's job belongs."
  value       = module.spark_operator.jobs_namespace
}

output "spark_service_account" {
  description = "Service account 3.5's SparkApplication manifest should reference (spec.driver/executor.serviceAccount)."
  value       = module.spark_job.service_account_name
}

output "spark_role_arn" {
  description = "cerberus-spark IAM role ARN, for reference/verification."
  value       = module.iam_spark.role_arn
}

output "nat_gateway_id" {
  description = "NAT Gateway ID, for reference/verification."
  value       = module.vpc_nat.nat_gateway_id
}

output "grafana_port_forward" {
  description = "7.7: how to reach Grafana (port-forward only, ADR 0016). Admin password: kubectl get secret -n monitoring grafana -o jsonpath='{.data.admin-password}' | base64 -d"
  value       = module.eks_observability.grafana_port_forward
}

output "prometheus_role_arn" {
  description = "7.7: cerberus-prometheus IRSA role ARN, for reference/verification."
  value       = module.eks_observability.prometheus_role_arn
}

output "grafana_role_arn" {
  description = "7.7: cerberus-grafana IRSA role ARN, for reference/verification."
  value       = module.eks_observability.grafana_role_arn
}
