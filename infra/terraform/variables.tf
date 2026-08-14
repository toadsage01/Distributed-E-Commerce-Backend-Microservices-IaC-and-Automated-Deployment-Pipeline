###############################################################################
# Input variables
###############################################################################

variable "aws_region" {
  description = "AWS region to deploy into. Pick one with all 3 AZs for HA."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment. Used as a name prefix + tag."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "environment must be one of: dev, stage, prod."
  }
}

variable "project_name" {
  description = "Prefix for all resource names. Keep short — AWS limit is 32 chars for some resources."
  type        = string
  default     = "ecom"
}

variable "aws_account_id" {
  description = "12-digit AWS account ID. Used to construct ECR + OIDC ARNs."
  type        = string
  # No default — must be provided via terraform.tfvars or -var.
}

###############################################################################
# VPC
###############################################################################

variable "vpc_cidr" {
  description = "CIDR for the VPC. /16 gives 65k IPs — plenty for a microservices deployment."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "AZs to spread across. Must be at least 2 for ALB + RDS HA."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "public_subnet_cidrs" {
  description = "Public subnets — for ALB + NAT GW. One per AZ."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "Private subnets — for EC2 + RDS + ElastiCache. One per AZ."
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
}

###############################################################################
# RDS
###############################################################################

variable "rds_instance_class" {
  description = "RDS instance size. db.t3.micro is free-tier-eligible (~$15/mo)."
  type        = string
  default     = "db.t3.micro"
}

variable "rds_db_name" {
  description = "Initial database name (one DB instance, schemas per service)."
  type        = string
  default     = "ecom"
}

variable "rds_username" {
  description = "Master DB username. Stored in Secrets Manager — not in source."
  type        = string
  default     = "ecom_admin"
}

variable "rds_password" {
  description = "Master DB password. Marked sensitive — pass via -var or Secrets Manager."
  type        = string
  sensitive  = true
  # No default — must be provided.
}

###############################################################################
# ElastiCache Redis
###############################################################################

variable "redis_node_type" {
  description = "ElastiCache node size. cache.t3.micro is free-tier-eligible."
  type        = string
  default     = "cache.t3.micro"
}

###############################################################################
# EC2
###############################################################################

variable "ec2_instance_type" {
  description = "EC2 instance size. t3.micro is free-tier-eligible (~$8/mo each)."
  type        = string
  default     = "t3.micro"
}

variable "ec2_count" {
  description = "Number of EC2 instances behind the ALB. 2 minimum for zero-downtime deploy."
  type        = number
  default     = 2
}

variable "ec2_ami_id" {
  description = "AMI ID for EC2. Defaults to latest Amazon Linux 2023 — set explicitly for reproducibility."
  type        = string
  default     = ""  # empty → use SSM parameter lookup
}

variable "ec2_key_pair_name" {
  description = "EC2 key pair name for SSH access (used by deploy script)."
  type        = string
  # No default — must be provided.
}

###############################################################################
# ECR
###############################################################################

variable "ecr_image_tag_mutability" {
  description = "Whether to allow overwriting image tags. IMMUTABLE is safer for prod."
  type        = string
  default     = "MUTABLE"  # MUTABLE simplifies CI for resume-scope
}

###############################################################################
# GitHub OIDC (for passwordless AWS auth from GitHub Actions)
###############################################################################

variable "github_org" {
  description = "GitHub user/org that owns the repo. Used to scope the OIDC role."
  type        = string
  default     = "toadsage01"
}

variable "github_repo" {
  description = "GitHub repo name. OIDC role is scoped to this repo only."
  type        = string
  default     = "Distributed-E-Commerce-Backend-Microservices-IaC-and-Automated-Deployment-Pipeline"
}
