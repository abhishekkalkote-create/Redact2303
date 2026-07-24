provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "redactproof"
      Environment = var.env
      ManagedBy   = "terraform"
    }
  }
}

# WAFv2 web ACLs for CloudFront must be created in us-east-1 regardless of the app's
# home region — see modules/edge/main.tf.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "redactproof"
      Environment = var.env
      ManagedBy   = "terraform"
    }
  }
}
