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

module "cognito" {
  source        = "../../modules/cognito"
  name          = local.name
  domain_prefix = var.cognito_domain_prefix
  callback_urls = var.domain_name == "" ? ["http://localhost:3000"] : ["https://${var.domain_name}"]
  logout_urls   = var.domain_name == "" ? ["http://localhost:3000"] : ["https://${var.domain_name}"]
}

# ecs.app_security_group_id feeds aurora's ingress rule below, and aurora's connection
# details would naturally feed back into ecs's container environment — that's a cycle
# (ecs -> aurora -> ecs). Broken deliberately: DB wiring into api/worker env vars is left
# as a Phase 1 follow-up (once real images exist to actually configure), not threaded
# through here. See TODO below.
module "ecs" {
  source                = "../../modules/ecs"
  name                  = local.name
  region                = var.region
  vpc_id                = module.vpc.vpc_id
  public_subnet_ids     = module.vpc.public_subnet_ids
  private_subnet_ids    = module.vpc.private_subnet_ids
  task_role_policy_arns = [module.storage.per_org_kms_management_policy_arn]

  api_image = var.api_image != "" ? var.api_image : null
  web_image = var.web_image != "" ? var.web_image : null

  # TODO(Phase 1, once real images + a deploy pipeline exist): wire DB_HOST/DB_NAME (from
  # module.aurora) and DB_USER/DB_PASSWORD (from module.aurora.master_user_secret_arn) into
  # api_environment/api_secrets below. Deferred rather than done now specifically to avoid
  # the ecs<->aurora cycle noted above — do it via a separate `aws_ecs_task_definition`
  # revision update outside this same apply, or restructure the app security group to be
  # created independently of both modules first.
  api_environment = {
    ENV                   = var.env
    AWS_REGION            = var.region
    COGNITO_USER_POOL_ID  = module.cognito.user_pool_id
    COGNITO_APP_CLIENT_ID = module.cognito.app_client_id
    COGNITO_REGION        = var.region
    S3_CONTENT_BUCKET     = module.storage.bucket_name
    CORS_ORIGINS          = var.domain_name == "" ? "[\"http://localhost:3000\"]" : "[\"https://${var.domain_name}\"]"
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

  pagerduty_integration_email = var.pagerduty_integration_email

  tags = { Env = var.env }
}
