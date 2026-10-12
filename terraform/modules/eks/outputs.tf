output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded cluster CA certificate, for kubeconfig generation."
  value       = aws_eks_cluster.this.certificate_authority[0].data
}

output "node_role_arn" {
  description = "Worker node IAM role ARN."
  value       = aws_iam_role.node.arn
}

output "oidc_provider_arn" {
  description = "IAM OIDC provider ARN, for 3.4/3.5's IRSA-bound Spark service-account role."
  value       = aws_iam_openid_connect_provider.eks.arn
}

output "oidc_issuer_url" {
  description = "OIDC issuer URL, for 3.4/3.5's IRSA trust-policy condition."
  value       = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

output "kubernetes_version" {
  description = "The cluster's Kubernetes minor version (e.g. 1.33) -- Cluster Autoscaler's image must match it."
  value       = aws_eks_cluster.this.version
}

output "executor_taint_key" {
  description = "Taint key on the Spot executor nodes."
  value       = var.executor_taint_key
}

output "executor_node_group_name" {
  description = "The Spot executor node group's name -- EKS tags its instances eks:nodegroup-name with it (the FIS Spot interruption test targets that tag)."
  value       = aws_eks_node_group.executors.node_group_name
}
