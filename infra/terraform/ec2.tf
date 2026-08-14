###############################################################################
# EC2 instances
#
# `ec2_count` instances (default 2) behind the ALB. Each runs the full
# stack via docker-compose (all 4 services + the gateway). This is the
# simplest real-world topology — rolling deploy updates one instance at
# a time, with health checks before moving to the next.
#
# Trade-off: running all services on every instance is "monolith-deployed-
# as-microservices" rather than true per-service scaling. For resume-scope
# this is fine and demonstrates the pattern. Real prod would use ECS or
# EKS with per-service task counts.
###############################################################################

# ---------- AMI lookup (Amazon Linux 2023) ----------
# Use SSM parameter store to get the latest AL2023 AMI. This auto-updates
# as new AMIs are released. Pin to a specific AMI for reproducibility.
data "aws_ami" "amazon_linux_2023" {
  count       = var.ec2_ami_id == "" ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

locals {
  ami_id = var.ec2_ami_id != "" ? var.ec2_ami_id : data.aws_ami.amazon_linux_2023[0].id
}

# ---------- EC2 instances ----------
resource "aws_instance" "app" {
  count                       = var.ec2_count
  ami                         = local.ami_id
  instance_type              = var.ec2_instance_type
  subnet_id                  = aws_subnet.private[count.index % length(aws_subnet.private)].id
  vpc_security_group_ids     = [aws_security_group.ec2.id]
  key_name                    = var.ec2_key_pair_name
  associate_public_ip_address = false  # private subnet — no public IP
  iam_instance_profile        = aws_iam_instance_profile.ec2.name

  # user_data is in user_data/ec2_bootstrap.sh — see that file for what it does
  user_data = templatefile(
    "${path.module}/user_data/ec2_bootstrap.sh.tftpl",
    {
      project_name       = var.project_name
      environment        = var.environment
      aws_region         = var.aws_region
      aws_account_id     = var.aws_account_id
      rds_endpoint       = aws_db_instance.main.address
      rds_secret_arn     = aws_secretsmanager_secret.rds_master.arn
      redis_endpoint     = aws_elasticache_replication_group.main.configuration_endpoint_address
      jwt_secret         = "REPLACE_VIA_SECRETS_MANAGER_AT_RUNTIME"
      ecr_repos          = local.service_names
    }
  )

  # Need enough disk for docker images + container layers.
  # 30GB is the minimum that doesn't fill up after a few deploys.
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true

    tags = {
      Name = "${var.project_name}-${var.environment}-ec2-${count.index + 1}-root"
    }
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ec2-${count.index + 1}"
    # Used by deploy script to find instances for rolling update
    DeployGroup = "${var.project_name}-${var.environment}"
    DeployIndex = count.index
  }

  # Make sure VPC + RDS + Redis + ECR exist before EC2 tries to use them.
  depends_on = [
    aws_db_instance.main,
    aws_elasticache_replication_group.main,
    aws_ecr_repository.services,
    aws_iam_instance_profile.ec2,
  ]
}

# ---------- Register EC2 instances with ALB target group ----------
resource "aws_lb_target_group_attachment" "app" {
  count            = var.ec2_count
  target_group_arn = aws_lb_target_group.gateway.arn
  target_id        = aws_instance.app[count.index].id
  port             = 8000
}
