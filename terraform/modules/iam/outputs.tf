output "role_arns" {
  description = "Map of role name -> ARN (ingestion/transform/serving/ingestion_lambda/spark)."
  value = {
    ingestion        = aws_iam_role.ingestion.arn
    transform        = aws_iam_role.transform.arn
    serving          = aws_iam_role.serving.arn
    ingestion_lambda = aws_iam_role.ingestion_lambda.arn
    spark            = aws_iam_role.spark.arn
  }
}
