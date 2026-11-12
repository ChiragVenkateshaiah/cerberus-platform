# No secrets here: the Cognito client secret is read by the instance itself
# (plan 2026-11-12, option 4.2 A) and never reaches state outputs.

output "session_url" {
  description = "The session's Grafana URL. Resolves only after the readiness probe and live.json."
  value       = "https://${aws_cloudfront_distribution.this.domain_name}/"

  depends_on = [aws_s3_object.live]
}

output "ends" {
  description = "When the session ends (UTC, RFC 3339): the time it went live plus var.minutes."
  value       = local.ends
}

output "instance_id" {
  description = "The Grafana host's instance ID (debug with SSM Session Manager; there is no SSH)."
  value       = aws_instance.grafana.id
}
