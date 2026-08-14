###############################################################################
# Security groups
#
# Traffic flow:
#   Internet → ALB (port 80/443)
#   ALB → EC2 (port 8000 — the gateway container)
#   EC2 → RDS (port 5432)
#   EC2 → ElastiCache (port 6379)
#   EC2 → EC2 (for inter-service HTTP — gateway → user/product/order)
#       NOTE: inter-service HTTP is on localhost via docker-compose networking
#       on each EC2 host, so technically doesn't need SG ingress. But if you
#       split services across hosts later, this rule is ready.
###############################################################################

# ---------- ALB SG ----------
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-${var.environment}-alb-sg"
  description = "ALB security group — public HTTP/HTTPS ingress"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All egress — ALB forwards to EC2 on port 8000"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-alb-sg"
  }
}

# ---------- EC2 SG ----------
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-${var.environment}-ec2-sg"
  description = "EC2 security group — accepts traffic from ALB + SSH from anywhere (lock down in prod)"
  vpc_id      = aws_vpc.main.id

  # HTTP from ALB only — the gateway container listens on 8000
  ingress {
    description     = "Gateway HTTP from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # Inter-service HTTP (gateway → downstream services on same host)
  # When all services run on one EC2 host via docker-compose, they
  # communicate over the docker bridge network — no SG ingress needed.
  # This rule allows future multi-host topologies.
  ingress {
    description = "Inter-service HTTP from other EC2 hosts"
    from_port   = 8001
    to_port     = 8003
    protocol    = "tcp"
    self        = true  # only from instances with this same SG
  }

  # SSH — lock this down to a bastion / your IP in prod!
  # Open to 0.0.0.0/0 here for resume-scope convenience.
  ingress {
    description = "SSH (lock down in prod)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All egress — apt, docker pull, S3, ECR, etc."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ec2-sg"
  }
}

# ---------- RDS SG ----------
resource "aws_security_group" "rds" {
  name        = "${var.project_name}-${var.environment}-rds-sg"
  description = "RDS Postgres — accepts connections from EC2 only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from EC2"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-rds-sg"
  }
}

# ---------- ElastiCache SG ----------
resource "aws_security_group" "redis" {
  name        = "${var.project_name}-${var.environment}-redis-sg"
  description = "ElastiCache Redis — accepts connections from EC2 only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from EC2"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-redis-sg"
  }
}
