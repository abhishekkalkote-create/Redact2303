output "alb_dns_name" {
  value = module.ecs.alb_dns_name
}

output "cloudfront_domain_name" {
  value = module.edge.distribution_domain_name
}

output "cognito_user_pool_id" {
  value = module.cognito.user_pool_id
}

output "cognito_app_client_id" {
  value = module.cognito.app_client_id
}

output "db_cluster_endpoint" {
  value = module.aurora.cluster_endpoint
}

output "db_master_user_secret_arn" {
  value = module.aurora.master_user_secret_arn
}

output "content_bucket_name" {
  value = module.storage.bucket_name
}

output "sqs_queue_urls" {
  value = module.queues.queue_urls
}

output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}
