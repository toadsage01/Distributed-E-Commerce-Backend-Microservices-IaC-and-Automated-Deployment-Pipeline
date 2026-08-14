#!/usr/bin/env bash
###############################################################################
# Rolling deploy script — invoked by .github/workflows/deploy.yml
#
# Strategy:
#   1. Find EC2 instances registered to the target group (sorted by DeployIndex tag)
#   2. For each instance:
#      a. Deregister from ALB target group → no new traffic
#      b. Wait ~10s for in-flight requests to drain
#      c. Send SSM Run Command: `docker compose pull && docker compose up -d`
#      d. Wait for local /health to return 200
#      e. Re-register with ALB target group
#      f. Wait for ALB health check to pass (target becomes "healthy")
#   3. If any instance fails, abort + alert (manual rollback)
#
# Required env vars:
#   AWS_REGION        — e.g. "us-east-1"
#   TARGET_GROUP_ARN  — ARN of the ALB target group
#   IMAGE_TAG         — image tag to deploy (default: latest)
###############################################################################
set -euo pipefail

REGION="${AWS_REGION:?AWS_REGION must be set}"
TG_ARN="${TARGET_GROUP_ARN:?TARGET_GROUP_ARN must be set}"
TAG="${IMAGE_TAG:-latest}"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# ---------- Find EC2 instances registered to the target group ----------
log "Discovering targets in $TG_ARN..."
TARGETS=$(aws elbv2 describe-target-health \
    --region "$REGION" \
    --target-group-arn "$TG_ARN" \
    --query 'TargetHealthDescriptions[].Target.Id' \
    --output text)

if [[ -z "$TARGETS" ]]; then
    log "❌ No targets found in target group"
    exit 1
fi

INSTANCE_IDS=($TARGETS)
# Sort by DeployIndex tag so we always deploy in the same order
SORTED_IDS=()
for id in "${INSTANCE_IDS[@]}"; do
    idx=$(aws ec2 describe-instances \
        --region "$REGION" \
        --instance-ids "$id" \
        --query 'Reservations[0].Instances[0].Tags[?Key==`DeployIndex`].Value' \
        --output text 2>/dev/null || echo "999")
    SORTED_IDS+=("$idx:$id")
done
IFS=$'\n' SORTED=($(sort -n <<< "${SORTED_IDS[*]}"))
unset IFS

# ---------- Deploy to each instance sequentially ----------
for entry in "${SORTED[@]}"; do
    INSTANCE_ID="${entry#*:}"
    log "────────── Deploying to $INSTANCE_ID ──────────"

    # 1. Deregister from ALB
    log "Deregistering $INSTANCE_ID from target group..."
    aws elbv2 deregister-targets \
        --region "$REGION" \
        --target-group-arn "$TG_ARN" \
        --targets Id="$INSTANCE_ID"

    # 2. Drain — give in-flight requests time to finish
    log "Waiting 10s for in-flight requests to drain..."
    sleep 10

    # 3. Pull new images + restart containers via SSM Run Command
    log "Triggering docker compose pull + up on $INSTANCE_ID..."
    COMMAND_ID=$(aws ssm send-command \
        --region "$REGION" \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters "commands=[\
            \"cd /opt/ecom\",\
            \"aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com\",\
            \"docker compose pull\",\
            \"docker compose up -d --remove-orphans\",\
            \"docker image prune -f\"\
        ]" \
        --query 'Command.CommandId' \
        --output text)

    # 4. Wait for SSM command to complete
    log "Waiting for SSM command $COMMAND_ID..."
    for i in $(seq 1 60); do
        STATUS=$(aws ssm get-command-invocation \
            --region "$REGION" \
            --command-id "$COMMAND_ID" \
            --instance-id "$INSTANCE_ID" \
            --query 'Status' \
            --output text 2>/dev/null || echo "Pending")

        if [[ "$STATUS" == "Success" ]]; then
            log "✅ SSM command succeeded"
            break
        elif [[ "$STATUS" == "Failed" || "$STATUS" == "Cancelled" || "$STATUS" == "TimedOut" ]]; then
            log "❌ SSM command $STATUS — aborting deploy"
            # Re-register so this instance keeps serving old code (if it's still up)
            aws elbv2 register-targets --region "$REGION" --target-group-arn "$TG_ARN" --targets Id="$INSTANCE_ID"
            exit 1
        fi
        sleep 5
    done

    # 5. Wait for local /health to return 200 (instance is back up)
    log "Waiting for instance /health to return 200..."
    HEALTH_COMMAND_ID=$(aws ssm send-command \
        --region "$REGION" \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters "commands=[\
            \"for i in \\$(seq 1 30); do\",\
            \"  if curl -fsS http://localhost:8000/health > /dev/null 2>&1; then echo OK; exit 0; fi\",\
            \"  sleep 2\",\
            \"done\",\
            \"echo TIMEOUT; exit 1\"\
        ]" \
        --query 'Command.CommandId' \
        --output text)

    for i in $(seq 1 30); do
        STATUS=$(aws ssm get-command-invocation \
            --region "$REGION" \
            --command-id "$HEALTH_COMMAND_ID" \
            --instance-id "$INSTANCE_ID" \
            --query 'Status' \
            --output text 2>/dev/null || echo "Pending")
        if [[ "$STATUS" == "Success" ]]; then
            log "✅ Instance healthy"
            break
        elif [[ "$STATUS" == "Failed" ]]; then
            log "❌ Instance failed to come up — keeping it deregistered"
            exit 1
        fi
        sleep 5
    done

    # 6. Re-register with ALB
    log "Re-registering $INSTANCE_ID with target group..."
    aws elbv2 register-targets \
        --region "$REGION" \
        --target-group-arn "$TG_ARN" \
        --targets Id="$INSTANCE_ID"

    # 7. Wait for ALB health check to mark it healthy
    log "Waiting for ALB health check to pass..."
    for i in $(seq 1 40); do
        HEALTH=$(aws elbv2 describe-target-health \
            --region "$REGION" \
            --target-group-arn "$TG_ARN" \
            --targets Id="$INSTANCE_ID" \
            --query 'TargetHealthDescriptions[0].TargetHealth.State' \
            --output text)
        if [[ "$HEALTH" == "healthy" ]]; then
            log "✅ $INSTANCE_ID is healthy in ALB"
            break
        fi
        sleep 5
    done

    log "✅ Deploy complete for $INSTANCE_ID"
done

log "🎉 All instances deployed successfully"
