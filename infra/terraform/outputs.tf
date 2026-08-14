###############################################################################
# Outputs — values you need after `terraform apply` to wire up CI/CD
###############################################################################

output "vpc_id" {
  description = "ID of the created VPC"
  value       = aws_vpc.main.id
}

output "alb_dns_name" {
  description = "Public DNS name of the ALB — this is your API endpoint"
  value       = aws_lb.main.dns_name
}

output "alb_arn" {
  description = "ALB ARN — used by deploy script"
  value       = aws_lb.main.arn
}

output "gateway_target_group_arn" {
  description = "ALB target group ARN for the gateway — used by deploy script"
  value       = aws_lb_target_group.gateway.arn
}

output "rds_endpoint" {
  description = "RDS Postgres endpoint — set this as DATABASE_URL host"
  value       = aws_db_instance.main.address
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint"
  value       = aws_elasticache_replication_group.main.configuration_endpoint_address
}

output "ecr_repository_urls" {
  description = "ECR repository URLs — used by CI to push images"
  value = {
    for name, repo in aws_ecr_repository.services :
    name => repo.repository_url
  }
}

output "ec2_instance_ids" {
  description = "EC2 instance IDs — used by deploy script for rolling update"
  value       = aws_instance.app[*].id
}

output "github_actions_role_arn" {
  description = "ARN of the GitHub OIDC role — set as AWS_ROLE_TO_ASSUME in GitHub secrets"
  value       = aws_iam_role.github_actions.arn
}

output "ec2_instance_profile_arn" {
  description = "Instance profile ARN — useful for debugging IAM issues"
  value       = aws_iam_instance_profile.ec2.arn
}

output "rds_secret_arn" {
  description = "Secrets Manager ARN for RDS master credentials"
  value       = aws_secretsmanager_secret.rds_master.arn
}

output "jwt_secret_arn" {
  description = "Secrets Manager ARN for JWT signing secret"
  value       = aws_secretsmanager_secret.jwt.arn
}
