###############################################################################
# Remote state backend
#
# State is stored in S3 with a DynamoDB lock table to prevent concurrent
# `terraform apply` runs from corrupting state.
#
# Setup (one-time, manual — DON'T run via terraform because terraform needs
# the bucket to exist before it can use it as a backend):
#
#   aws s3api create-bucket --bucket ecom-tfstate-${AWS_ACCOUNT_ID} --region ${AWS_REGION}
#   aws dynamodb create-table \
#       --table-name ecom-tfstate-lock \
#       --attribute-definitions AttributeName=LockID,AttributeType=S \
#       --key-schema AttributeName=LockID,KeyType=HASH \
#       --billing-mode PAY_PER_REQUEST
#
# Then create `backend.hcl` (git-ignored):
#
#   bucket = "ecom-tfstate-123456789012"
#   key    = "ecom/${var.environment}/terraform.tfstate"
#   region = "us-east-1"
#   dynamodb_table = "ecom-tfstate-lock"
#   encrypt = true
#
# And run `terraform init -backend-config=backend.hcl`.
###############################################################################

# This file is intentionally empty — the backend is configured via
# `-backend-config=` at init time so the bucket name stays out of source.
