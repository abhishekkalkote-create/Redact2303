variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "execution_secrets_arns" {
  description = "Secrets Manager ARNs referenced by api_secrets/web_secrets/worker_secrets - the task EXECUTION role (which injects `secrets` env vars at container start) needs GetSecretValue on these; AmazonECSTaskExecutionRolePolicy alone does not grant it."
  type        = list(string)
  default     = []
}

variable "certificate_arn" {
  description = "ACM cert for the ALB HTTPS listener. Empty until a domain is set up"
  type        = string
  default     = ""
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "task_role_policy_arns" {
  description = "Extra IAM policies attached to the shared ECS task role (e.g. per-org KMS management, SQS, S3 access)"
  type        = list(string)
  default     = []
}

# --- api ---
variable "api_image" {
  description = "Placeholder until CI publishes a real image to ECR (see .github/workflows/deploy.yml)"
  type        = string
  default     = "public.ecr.aws/docker/library/httpd:2.4"
  nullable    = false
}
variable "api_container_port" {
  type    = number
  default = 8000
}
variable "api_cpu" {
  type    = number
  default = 512
}
variable "api_memory" {
  type    = number
  default = 1024
}
variable "api_desired_count" {
  type    = number
  default = 1
}
variable "api_environment" {
  type    = map(string)
  default = {}
}
variable "api_secrets" {
  description = "Map of env var name -> Secrets Manager/SSM ARN"
  type        = map(string)
  default     = {}
}

# --- web ---
variable "web_image" {
  type     = string
  default  = "public.ecr.aws/docker/library/httpd:2.4"
  nullable = false
}
variable "web_container_port" {
  type    = number
  default = 3000
}
variable "web_cpu" {
  type    = number
  default = 512
}
variable "web_memory" {
  type    = number
  default = 1024
}
variable "web_desired_count" {
  type    = number
  default = 1
}
variable "web_environment" {
  type    = map(string)
  default = {}
}

# --- worker ---
variable "worker_image" {
  type     = string
  default  = "public.ecr.aws/docker/library/httpd:2.4"
  nullable = false
}
variable "worker_cpu" {
  type    = number
  default = 1024
}
variable "worker_memory" {
  type    = number
  default = 2048
}
variable "worker_desired_count" {
  type    = number
  default = 0 # nothing to run until Phase 1's worker code exists
}
variable "worker_environment" {
  type    = map(string)
  default = {}
}
variable "worker_secrets" {
  type    = map(string)
  default = {}
}

variable "tags" {
  type    = map(string)
  default = {}
}
