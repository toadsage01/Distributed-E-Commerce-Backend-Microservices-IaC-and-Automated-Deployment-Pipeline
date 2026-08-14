###############################################################################
# ECR repositories — one per service image
#
# CI builds push here, EC2 pulls from here. Separate repos per service
# (rather than one repo with multiple tags) so we can set per-service
# lifecycle policies (e.g. keep last 10 user-service images, last 5 of
# others).
###############################################################################

locals {
  service_names = ["user-service", "product-service", "order-service", "api-gateway"]
}

resource "aws_ecr_repository" "services" {
  for_each             = toset(local.service_names)
  name                 = "${var.project_name}/${each.value}"
  image_tag_mutability = var.ecr_image_tag_mutability
  force_delete         = true  # let `terraform destroy` clean up even with images

  image_scanning_configuration {
    scan_on_push = true  # free, catches known-vulnerable base images
  }

  tags = {
    Name = "${var.project_name}-${each.value}"
  }
}

# ---------- Lifecycle policy: keep last 10 images, expire the rest ----------
# Saves cost (ECR charges per GB stored) and keeps the repo manageable.
resource "aws_ecr_lifecycle_policy" "services" {
  for_each   = toset(local.service_names)
  repository = aws_ecr_repository.services[each.key].id

  policy = jsonencode({
    rules = [
      {
        rule_id    = "keep-last-10"
        priority   = 1
        action     = { type = "expire" }
        selection  = {
          tag_status   = "tagged"
          tag_prefix_list = ["v", "sha-"]
          count_type    = "imageCountMoreThan"
          count_number  = 10
        }
        description = "Keep last 10 tagged images"
      },
      {
        rule_id    = "expire-untagged-after-7d"
        priority   = 2
        action     = { type = "expire" }
        selection  = {
          tag_status   = "untagged"
          count_type   = "sinceImagePushed"
          count_unit   = "days"
          count_number = 7
        }
        description = "Expire untagged images after 7 days"
      }
    ]
  })
}
