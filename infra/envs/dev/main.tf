locals {
  name = "redactproof-${var.env}"
}

module "vpc" {
  source = "../../modules/vpc"
  name   = local.name
}

module "storage" {
  source = "../../modules/storage"
  name   = local.name
}

module "queues" {
  source = "../../modules/queues"
  name   = local.name
}

module "ecr" {
  source           = "../../modules/ecr"
  name             = local.name
  repository_names = ["api", "web"]
  tags             = { Env = var.env }
}

# api/app/core/config.py refuses to boot outside env=="local" with these fields still at
# their checked-in-and-public placeholder values. Secret metadata only lives in
# Terraform/state - the actual value is set out-of-band via `aws secretsmanager
# put-secret-value` (same reasoning as module.aurora's master_user_secret: keep real
# secret material out of tfstate).
resource "aws_secretsmanager_secret" "api_certificate_signing_key" {
  name = "${local.name}-certificate-signing-key"
}

resource "aws_secretsmanager_secret" "api_internal_cron_secret" {
  name = "${local.name}-internal-cron-secret"
}

# Composed asyncpg URL (user:password@host:port/dbname), assembled out-of-band from
# module.aurora's endpoint + master_user_secret and put here via `aws secretsmanager
# put-secret-value` - see the ecs<->aurora cycle note below on why this resource is
# declared here (no dependency on module.aurora's attributes) rather than passed as a
# direct Terraform reference.
resource "aws_secretsmanager_secret" "api_database_url" {
  name = "${local.name}-database-url"
}

module "cognito" {
  source        = "../../modules/cognito"
  name          = local.name
  domain_prefix = var.cognito_domain_prefix
  callback_urls = var.domain_name == "" ? ["http://localhost:3000"] : ["https://${var.domain_name}"]
  logout_urls   = var.domain_name == "" ? ["http://localhost:3000"] : ["https://${var.domain_name}"]
}

# ecs.app_security_group_id feeds aurora's ingress rule below, and aurora's connection
# details would naturally feed back into ecs's container environment — that's a cycle
# (ecs -> aurora -> ecs). Resolved by NOT threading a direct Terraform reference through:
# api_secrets.DATABASE_URL points at aws_secretsmanager_secret.api_database_url (declared
# above, no dependency on module.aurora's attributes), and the actual connection string
# is assembled out-of-band from module.aurora's endpoint + master_user_secret and written
# in via `aws secretsmanager put-secret-value` after both modules exist.
module "ecs" {
  source                = "../../modules/ecs"
  name                  = local.name
  region                = var.region
  vpc_id                = module.vpc.vpc_id
  public_subnet_ids     = module.vpc.public_subnet_ids
  private_subnet_ids    = module.vpc.private_subnet_ids
  task_role_policy_arns = [module.storage.per_org_kms_management_policy_arn]
  execution_secrets_arns = [
    aws_secretsmanager_secret.api_certificate_signing_key.arn,
    aws_secretsmanager_secret.api_internal_cron_secret.arn,
    aws_secretsmanager_secret.api_database_url.arn,
  ]

  api_image = var.api_image != "" ? var.api_image : null
  web_image = var.web_image != "" ? var.web_image : null

  api_environment = {
    ENV                   = var.env
    AWS_REGION            = var.region
    COGNITO_USER_POOL_ID  = module.cognito.user_pool_id
    COGNITO_APP_CLIENT_ID = module.cognito.app_client_id
    COGNITO_REGION        = var.region
    S3_CONTENT_BUCKET     = module.storage.bucket_name
    CORS_ORIGINS          = var.domain_name == "" ? "[\"http://localhost:3000\"]" : "[\"https://${var.domain_name}\"]"
  }
  api_secrets = {
    CERTIFICATE_SIGNING_KEY = aws_secretsmanager_secret.api_certificate_signing_key.arn
    INTERNAL_CRON_SECRET    = aws_secretsmanager_secret.api_internal_cron_secret.arn
    DATABASE_URL            = aws_secretsmanager_secret.api_database_url.arn
  }

  worker_image = var.worker_image != "" ? var.worker_image : null
  worker_environment = {
    ENV               = var.env
    AWS_REGION        = var.region
    S3_CONTENT_BUCKET = module.storage.bucket_name
    SQS_INTAKE_URL    = module.queues.queue_urls["intake"]
    SQS_EXTRACT_URL   = module.queues.queue_urls["extract"]
    SQS_DETECT_URL    = module.queues.queue_urls["detect"]
    SQS_EXPORT_URL    = module.queues.queue_urls["export"]
    SQS_VERIFY_URL    = module.queues.queue_urls["verify"]
  }

  tags = { Env = var.env }
}

module "aurora" {
  source                 = "../../modules/aurora"
  name                   = local.name
  vpc_id                 = module.vpc.vpc_id
  private_subnet_ids     = module.vpc.private_subnet_ids
  app_security_group_ids = [module.ecs.app_security_group_id]
}

module "edge" {
  source = "../../modules/edge"
  providers = {
    aws = aws.us_east_1
  }
  name         = local.name
  alb_dns_name = module.ecs.alb_dns_name
  domain_name  = var.domain_name
}

module "alerting" {
  source = "../../modules/alerting"
  name   = local.name

  dlq_names                   = module.queues.dlq_names
  ecs_cluster_name            = module.ecs.cluster_name
  api_service_name            = module.ecs.api_service_name
  web_service_name            = module.ecs.web_service_name
  worker_service_name         = module.ecs.worker_service_name
  alb_arn_suffix              = module.ecs.alb_arn_suffix
  api_target_group_arn_suffix = module.ecs.api_target_group_arn_suffix
  web_target_group_arn_suffix = module.ecs.web_target_group_arn_suffix
  api_log_group_name          = module.ecs.api_log_group_name

  pagerduty_integration_email = var.pagerduty_integration_email

  tags = { Env = var.env }
}
