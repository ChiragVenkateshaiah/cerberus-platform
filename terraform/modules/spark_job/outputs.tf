output "service_account_name" {
  description = "Service account name, for the SparkApplication manifest's spec.driver/executor.serviceAccount."
  value       = kubernetes_service_account.spark.metadata[0].name
}
