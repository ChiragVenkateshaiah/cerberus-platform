module "s3_medallion" {
  source = "../../modules/s3_medallion"

  account_id = data.aws_caller_identity.current.account_id
}

module "iam" {
  source = "../../modules/iam"

  bucket_arns           = module.s3_medallion.bucket_arns
  trusted_principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/cerberus-admin"
}
