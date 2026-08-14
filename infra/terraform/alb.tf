###############################################################################
# Application Load Balancer
#
# Single ALB → 2 EC2 instances (round-robin). One target group per service
# port — for now we only route to the gateway (port 8000); other services
# are reached via the gateway, so they don't need their own target groups.
###############################################################################

# ---------- ALB ----------
resource "aws_lb" "main" {
  name               = "${var.project_name}-${var.environment}-alb"
  internal           = false  # public-facing — clients hit this directly
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # ALB access logs — useful for debugging 5xxs. Free bucket storage cost.
  # Comment out if you don't want to create the bucket.
  # access_logs {
  #   bucket  = aws_s3_bucket.alb_logs.id
  #   prefix  = "${var.project_name}-${var.environment}"
  #   enabled = true
  # }

  tags = {
    Name = "${var.project_name}-${var.environment}-alb"
  }

  depends_on = [aws_internet_gateway.main]
}

# ---------- Target group (gateway port 8000) ----------
resource "aws_lb_target_group" "gateway" {
  name        = "${var.project_name}-${var.environment}-gateway-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  # Health check — hits the gateway's /health endpoint
  health_check {
    enabled             = true
    path                = "/health"
    port                = "8000"
    protocol            = "HTTP"
    interval            = 15
    timeout             = 3
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  # Deregistration delay — give in-flight requests time to finish before
  # the target is fully removed during rolling deploy.
  deregistration_delay = 30

  tags = {
    Name = "${var.project_name}-${var.environment}-gateway-tg"
  }
}

# ---------- HTTP listener (port 80) ----------
# Redirects to HTTPS in prod. In dev, just serves HTTP directly.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }

  # NOTE: prod should add a redirect to HTTPS + a 443 listener with an ACM cert.
  # Skipped here to avoid requiring a domain name + ACM cert setup.
}

# ---------- Listener rule: forward /health to target group ----------
# Already covered by default_action above, but explicit rule makes it clear.
