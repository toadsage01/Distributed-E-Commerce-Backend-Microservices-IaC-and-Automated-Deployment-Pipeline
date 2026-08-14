###############################################################################
# IAM roles + policies
#
# Three roles:
#   1. EC2 instance profile — lets EC2 pull from ECR + read Secrets Manager
#   2. GitHub OIDC role — lets GitHub Actions assume into AWS without long-lived keys
#   3. (Future) per-service task roles if we move to ECS
###############################################################################

# ============================================================
# 1. EC2 instance profile
# ============================================================

# Trust policy — let EC2 assume this role
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2_role" {
  name               = "${var.project_name}-${var.environment}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = {
    Name = "${var.project_name}-${var.environment}-ec2-role"
  }
}

# ECR pull permissions — only pull from this project's repos
data "aws_iam_policy_document" "ec2_ecr" {
  statement {
    sid     = "PullFromProjectECR"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    # Restricted to our project's ECR repos only
    resources = [
      for name in local.service_names :
      "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/${var.project_name}/${name}"
    ]
  }
}

resource "aws_iam_policy" "ec2_ecr" {
  name        = "${var.project_name}-${var.environment}-ec2-ecr-policy"
  description = "Allow EC2 to pull from this project's ECR repos"
  policy      = data.aws_iam_policy_document.ec2_ecr.json
}

resource "aws_iam_role_policy_attachment" "ec2_ecr" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ec2_ecr.arn
}

# Secrets Manager read access (for RDS creds + any future secrets)
data "aws_iam_policy_document" "ec2_secrets" {
  statement {
    sid     = "ReadProjectSecrets"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    # Only secrets tagged with this project + environment
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}-${var.environment}-*",
    ]
  }
}

resource "aws_iam_policy" "ec2_secrets" {
  name        = "${var.project_name}-${var.environment}-ec2-secrets-policy"
  description = "Allow EC2 to read this project's Secrets Manager secrets"
  policy      = data.aws_iam_policy_document.ec2_secrets.json
}

resource "aws_iam_role_policy_attachment" "ec2_secrets" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ec2_secrets.arn
}

# SSM Session Manager access (so we can SSH via Session Manager if needed)
resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# CloudWatch Agent — push logs to CloudWatch
resource "aws_iam_role_policy_attachment" "ec2_cw" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# Instance profile — what EC2 actually references
resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-${var.environment}-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# ============================================================
# 2. GitHub OIDC role — for passwordless CI auth
# ============================================================

# OIDC provider for GitHub Actions (one per account, idempotent)
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  # Thumbprint from GitHub's docs — they rarely change.
  # AWS now manages this automatically for well-known providers.
  thumbprint_list = ["69ffce3fcb4ed0d1df3a2e0b24b74e3f6b9dff3a"]

  client_id_list = ["sts.amazonaws.com"]
}

# Trust policy — let the specific GitHub repo assume this role.
# Tight scoping prevents other repos from impersonating.
data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only allow the specific GitHub repo + branch to assume.
    # Use StringLike for repo + branch scoping — repo ref includes
    # the branch, so this is "main branch of this repo only".
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project_name}-${var.environment}-github-actions-role"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json

  tags = {
    Name = "${var.project_name}-${var.environment}-github-actions-role"
  }
}

# What GitHub Actions can do:
#   - Push to ECR (CI builds)
#   - Update EC2 (deploy via SSM Run Command — no SSH keys needed)
#   - Trigger ALB target group health checks (for zero-downtime deploy)
data "aws_iam_policy_document" "github_actions" {
  # ECR push
  statement {
    sid = "PushToProjectECR"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [
      for name in local.service_names :
      "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/${var.project_name}/${name}"
    ]
  }

  # EC2 deploy via SSM (no SSH key needed)
  statement {
    sid = "DeployViaSSM"
    actions = [
      "ssm:SendCommand",
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
    ]
    resources = [
      "arn:aws:ec2:${var.aws_region}:${var.aws_account_id}:instance/*",
      "arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:document/AWS-RunShellScript",
    ]
  }

  # ALB target group — deregister/register for rolling deploy
  statement {
    sid = "ManageTargetGroups"
    actions = [
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth",
      "elasticloadbalancing:DeregisterTargets",
      "elasticloadbalancing:RegisterTargets",
    ]
    resources = ["*"]
  }

  # Read EC2 instance IDs (to find targets)
  statement {
    sid = "DescribeEC2ForDeploy"
    actions = [
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceStatus",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "github_actions" {
  name        = "${var.project_name}-${var.environment}-github-actions-policy"
  description = "Permissions for GitHub Actions CI/CD role"
  policy      = data.aws_iam_policy_document.github_actions.json
}

resource "aws_iam_role_policy_attachment" "github_actions" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions.arn
}
