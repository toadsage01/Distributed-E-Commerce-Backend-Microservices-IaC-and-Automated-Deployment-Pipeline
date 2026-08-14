###############################################################################
# RDS Postgres
#
# One DB instance shared by all services, with separate schemas per service
# (users, products, orders). Trade-off: not "true" database-per-service, but
# realistic for resume-scope and avoids 3x RDS cost. See ARCHITECTURE.md.
#
# The password is stored in Secrets Manager and rotated automatically. EC2
# retrieves it via IAM role (no secrets baked into user_data).
###############################################################################

# ---------- DB subnet group (private subnets only) ----------
resource "aws_db_subnet_group" "main" {
  name        = "${var.project_name}-${var.environment}-db-subnet-group"
  description = "Private subnets for RDS Postgres"
  subnet_ids  = aws_subnet.private[*].id

  tags = {
    Name = "${var.project_name}-${var.environment}-db-subnet-group"
  }
}

# ---------- Secrets Manager: store master password ----------
# Stored separately from the RDS resource so we can rotate it without
# recreating the DB.
resource "aws_secretsmanager_secret" "rds_master" {
  name        = "${var.project_name}-${var.environment}-rds-master"
  description = "Master credentials for the RDS Postgres instance"

  # Auto-recovery keeps the secret around for 7 days after deletion —
  # prevents accidental permanent deletion.
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-rds-master-secret"
  }
}

resource "aws_secretsmanager_secret_version" "rds_master" {
  secret_id = aws_secretsmanager_secret.rds_master.id

  secret_string = jsonencode({
    username = var.rds_username
    password = var.rds_password
    engine   = "postgres"
    host     = aws_db_instance.main.address
    port     = 5432
    dbname   = var.rds_db_name
    dbSchema = "users,products,orders"
  })
}

# ---------- RDS instance ----------
resource "aws_db_instance" "main" {
  identifier                 = "${var.project_name}-${var.environment}-postgres"
  engine                     = "postgres"
  engine_version             = "16.4"
  instance_class             = var.rds_instance_class
  allocated_storage          = 20
  storage_type               = "gp3"
  storage_encrypted          = true

  db_name                    = var.rds_db_name
  username                   = var.rds_username
  password                   = var.rds_password  # also stored in Secrets Manager
  manage_master_user_password = false  # we manage it manually for clarity

  db_subnet_group_name       = aws_db_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.rds.id]

  multi_az                   = var.environment == "prod" ? true : false  # cost: ~2x
  backup_retention_period    = var.environment == "prod" ? 7 : 1
  deletion_protection        = var.environment == "prod"

  # Auto-minor-version-upgrade applies patches in the maintenance window.
  # Keep enabled unless you have a strict change-freeze process.
  auto_minor_version_upgrade = true
  maintenance_window         = "sun:03:00-sun:04:00"  # 3-4 AM UTC Sunday

  # Skip final snapshot on `terraform destroy` — for dev/stage only.
  # Prod should set this to false so destroy requires explicit cleanup.
  skip_final_snapshot = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${var.project_name}-${var.environment}-final-snapshot" : null

  tags = {
    Name = "${var.project_name}-${var.environment}-postgres"
  }

  # Don't expose RDS until the SG + subnet group exist.
  depends_on = [
    aws_security_group.rds,
    aws_db_subnet_group.main,
  ]
}
