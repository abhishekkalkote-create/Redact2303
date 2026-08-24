variable "name" {
  type = string
}

variable "repository_names" {
  description = "Suffixes appended to \"<name>-\" for each ECR repository to create."
  type        = list(string)
}

variable "tags" {
  type    = map(string)
  default = {}
}
