###############################################################################
# Secrets Manager — JWT signing secret
#
# Stored separately from RDS creds. Both EC2 + GitHub Actions read this
# at runtime — no secrets in source, no secrets in user_data.
###############################################################################

resource "aws_secretsmanager_secret" "jwt" {
  name        = "${var.project_name}-${var.environment}-jwt"
  description = "JWT signing secret for ${var.environment}"

  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-jwt-secret"
  }
}

resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id = aws_secretsmanager_secret.jwt.id

  # Generate a random secret at apply time. If you want to set this
  # manually, override with: terraform apply -var="jwt_secret_value=..."
  secret_string = random_password.jwt_secret.result
}

resource "random_password" "jwt_secret" {
  length  = 64
  special = false  # avoid URL-unsafe chars in env vars
}
