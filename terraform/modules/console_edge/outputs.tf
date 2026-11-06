output "site_bucket_name" {
  description = "Site bucket name -- 9.4's publish syncs the built site here."
  value       = aws_s3_bucket.site.id
}

output "distribution_id" {
  description = "CloudFront distribution ID -- 9.4's publish invalidates it."
  value       = aws_cloudfront_distribution.this.id
}

output "distribution_domain_name" {
  description = "CloudFront domain name (<id>.cloudfront.net) -- the console's only public address."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "user_pool_id" {
  description = "Cognito user pool ID -- the owner creates invited users here with admin-create-user."
  value       = aws_cognito_user_pool.this.id
}

output "client_id" {
  description = "Cognito app client ID of the SPA."
  value       = aws_cognito_user_pool_client.spa.id
}

output "auth_domain" {
  description = "Cognito hosted-UI base URL."
  value       = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.region}.amazoncognito.com"
}

output "callback_url" {
  description = "The app client's sign-in redirect URL."
  value       = local.callback_url
}

output "api_id" {
  description = "HTTP API ID."
  value       = aws_apigatewayv2_api.this.id
}

output "command_function_name" {
  description = "Command Lambda name."
  value       = aws_lambda_function.command.function_name
}
