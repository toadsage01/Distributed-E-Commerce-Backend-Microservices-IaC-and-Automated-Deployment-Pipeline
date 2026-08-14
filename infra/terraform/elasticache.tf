###############################################################################
# ElastiCache Redis (for slowapi rate-limit counters)
#
# Single-node (non-clustered) mode — sufficient for our volume and the
# slowapi library doesn't need cluster mode. Multi-AZ only in prod.
###############################################################################

resource "aws_elasticache_subnet_group" "main" {
  name        = "${var.project_name}-${var.environment}-redis-subnet-group"
  description = "Private subnets for ElastiCache Redis"
  subnet_ids  = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id          = "${var.project_name}-${var.environment}-redis"
  description                   = "Rate-limit + cache Redis for ${var.environment}"
  node_type                     = var.redis_node_type
  port                          = 6379
  parameter_group_name          = "default.redis7"
  engine_version                = "7.1"

  subnet_group_name             = aws_elasticache_subnet_group.main.name
  security_group_ids            = [aws_security_group.redis.id]

  # Single-node (no read replicas) for dev/stage; multi-AZ with replica for prod.
  num_cache_clusters            = var.environment == "prod" ? 2 : 1
  automatic_failover_enabled    = var.environment == "prod"
  multi_az_enabled              = var.environment == "prod"

  # Encryption at rest + in transit — both free, no reason to skip.
  at_rest_encryption_enabled    = true
  transit_encryption_enabled    = false  # would require TLS-aware Redis client

  # No auth token for dev (simpler — security group protects it).
  # Prod should set `auth_token` and configure slowapi to use it.
  apply_immediately             = var.environment != "prod"  # don't disrupt prod

  tags = {
    Name = "${var.project_name}-${var.environment}-redis"
  }

  depends_on = [
    aws_security_group.redis,
    aws_elasticache_subnet_group.main,
  ]
}
