###############################################################################
# Versions + providers
###############################################################################

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }

  # Remote state — see backend.tf for the S3 + DynamoDB config.
  # NOTE: this is intentionally NOT defined here. Run `terraform init` with
  # `-backend-config=...` from a backend config file (infra/terraform/backend.hcl,
  # git-ignored) so the bucket name doesn't get baked into source. This
  # lets multiple environments (dev/stage/prod) share the same module.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "ecom-microservices"
      Environment = var.environment
      ManagedBy   = "terraform"
      Repo        = "Distributed-E-Commerce-Backend-Microservices-IaC-and-Automated-Deployment-Pipeline"
    }
  }
}
