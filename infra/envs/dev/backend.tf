# Partial backend config — bucket/key/region/dynamodb_table are supplied via
# `terraform init -backend-config=backend.hcl` (gitignored; see backend.hcl.example),
# because Terraform backend blocks can't reference variables. The bucket + lock table
# must exist BEFORE `terraform init` here — that's a one-time manual bootstrap step,
# since Terraform can't create the backend it's about to store its own state in.
terraform {
  backend "s3" {}
}
