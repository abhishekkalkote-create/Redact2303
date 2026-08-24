# One repository per deployable image (api, web, ... worker once it exists as a real
# codebase - see envs/dev/main.tf and specs/10-build-plan.md). Image scanning on push
# and a lifecycle policy (keep last 10 untagged, expire nothing tagged) keep repos from
# growing unbounded without deleting anything a rollback might need.
resource "aws_ecr_repository" "this" {
  for_each             = toset(var.repository_names)
  name                 = "${var.name}-${each.key}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images after 10 newer untagged images exist"
      selection = {
        tagStatus   = "untagged"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
