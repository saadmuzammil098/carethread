output "function_name" {
  value = module.carethread_api.function_name
}

output "function_url" {
  value = module.carethread_api.function_url
}

output "ecr_repository_url" {
  value = module.carethread_api.ecr_repository_url
}

output "iam_role_arn" {
  value = module.carethread_api.iam_role_arn
}

output "published_version" {
  value = module.carethread_api.version
}

output "live_alias_arn" {
  value = aws_lambda_alias.live.arn
}
