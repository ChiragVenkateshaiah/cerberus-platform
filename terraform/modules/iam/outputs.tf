output "role_arns" {
  description = "Map of role name -> ARN (ingestion/transform/serving)."
  value = {
    ingestion = aws_iam_role.ingestion.arn
    transform = aws_iam_role.transform.arn
    serving   = aws_iam_role.serving.arn
  }
}
