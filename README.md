# Distributed E-Commerce Backend — Microservices, IaC & Automated Deployment

A production-style e-commerce backend built as four microservices behind a
single API Gateway, with full Infrastructure-as-Code (Terraform) and a
zero-downtime CI/CD pipeline (GitHub Actions → ECR → SSM rolling deploy).

Built to be **real, not a toy** — every architectural decision in the spec
is implemented as it would be in production.

## Architecture

```
                        ┌─────────────────────┐
   Client ───────────►  │   API Gateway (FastAPI) │
                        │  - JWT verification      │
                        │  - API key check          │
                        │  - Redis rate limiter      │
                        │  - Request routing          │
                        └──────┬──────┬──────┬────────┘
                               │      │      │
                    ┌──────────┘      │      └──────────┐
                    ▼                 ▼                 ▼
            ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
            │ User Service  │ │Product Service│ │ Order Service │
            │ (FastAPI)     │ │ (FastAPI)     │ │ (FastAPI)     │
            │ - auth/signup │ │ - catalog CRUD│ │ - order flow  │
            │ - issues JWT  │ │               │ │ - calls User/ │
            │               │ │               │ │   Product     │
            └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
                    │                 │                 │
                    └────────┬────────┴─────────┬───────┘
                             ▼                   ▼
                     ┌──────────────┐   ┌────────────────┐
                     │ RDS Postgres │   │ ElastiCache Redis │
                     │ (private     │   │ (rate-limit cache) │
                     │  subnet)     │   │                    │
                     └──────────────┘   └────────────────┘
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design
rationale, trade-offs, and what would change for a real production scale-up.

## Repository layout

```
.
├── services/                       # Four FastAPI microservices
│   ├── shared/                     # Shared lib (config, JWT, DB) — installed as `shared`
│   ├── user-service/               # Auth + JWT issuance + API key management
│   ├── product-service/            # Catalog CRUD + stock reservation
│   ├── order-service/              # Order flow + inter-service httpx calls
│   └── api-gateway/                # JWT verify + slowapi rate limit + reverse proxy
├── infra/
│   └── terraform/                  # VPC, RDS, ElastiCache, ALB, EC2, ECR, IAM, S3 backend
├── .github/workflows/              # CI (pytest) + Deploy (build→push→rolling)
├── scripts/
│   └── deploy_rolling.sh           # SSM-based zero-downtime rolling deploy
├── load_tests/                     # Locust 500-concurrent-user load test
├── docker-compose.yml              # Local dev parity with prod
└── docs/ARCHITECTURE.md
```

## Quick start (local)

```bash
# 1. Build + start everything (postgres + redis + 4 services)
docker compose up --build

# 2. Signup → get tokens
curl -X POST http://localhost:8000/auth/signup \
    -H 'Content-Type: application/json' \
    -d '{"email":"alice@example.com","full_name":"Alice","password":"supersecret123"}'
# → {"access_token":"...","refresh_token":"...","token_type":"bearer","expires_in":900}

# 3. Create an API key (use the access_token from step 2)
curl -X POST http://localhost:8000/auth/api-keys \
    -H 'Authorization: Bearer <ACCESS_TOKEN>' \
    -H 'Content-Type: application/json' \
    -d '{"label":"my-app"}'
# → {"id":1,"user_id":1,"label":"my-app","key":"sk_..."}

# 4. Create a product (needs both API key + Bearer token)
curl -X POST http://localhost:8000/products \
    -H "X-API-Key: sk_..." \
    -H "Authorization: Bearer <ACCESS_TOKEN>" \
    -H 'Content-Type: application/json' \
    -d '{"name":"Widget","price":"19.99","stock":100}'
# → {"id":1,"name":"Widget","price":19.99,"stock":100,...}

# 5. List products (public — no auth needed)
curl http://localhost:8000/products

# 6. Place an order (calls User + Product via httpx under the hood)
curl -X POST http://localhost:8000/orders \
    -H "X-API-Key: sk_..." \
    -H "Authorization: Bearer <ACCESS_TOKEN>" \
    -H 'Content-Type: application/json' \
    -d '{"items":[{"product_id":1,"quantity":2}]}'
```

API docs at http://localhost:8000/docs (Swagger UI).

## Running tests

```bash
# All services (29 tests total)
for svc in user-service product-service order-service api-gateway; do
    DATABASE_URL="sqlite:///./test.db" REDIS_URL="memory://" JWT_SECRET="test" \
    PYTHONPATH="$(pwd):$(pwd)/services/$svc" \
    python -m pytest services/$svc/tests/ -q
done
```

Tests use SQLite + in-memory Redis — no Docker or Postgres required.

## Load testing

```bash
cd load_tests
pip install -r requirements.txt

# Make sure the stack is up
docker compose up --build -d

# Run 500 concurrent users for 5 minutes
locust -f locustfile.py --host=http://localhost:8000 \
    --headless -u 500 -r 8 -t 300s \
    --html=report.html --csv=report
```

See [`load_tests/README.md`](load_tests/README.md) for expected results.

## Deploying to AWS

### 1. Set up Terraform backend (one-time)

```bash
# Create the S3 bucket + DynamoDB lock table for remote state
aws s3api create-bucket --bucket ecom-tfstate-$(aws sts get-caller-identity --query Account --output text) --region us-east-1
aws dynamodb create-table \
    --table-name ecom-tfstate-lock \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
```

### 2. Configure Terraform variables

```bash
cd infra/terraform

# Copy the example tfvars + fill in real values
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set aws_account_id, rds_password, ec2_key_pair_name

# Create backend.hcl (git-ignored) pointing to your S3 + DynamoDB
cat > backend.hcl <<EOF
bucket = "ecom-tfstate-YOUR_ACCOUNT_ID"
key    = "ecom/dev/terraform.tfstate"
region = "us-east-1"
dynamodb_table = "ecom-tfstate-lock"
encrypt = true
EOF
```

### 3. Provision the infrastructure

```bash
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

Outputs include `alb_dns_name`, `github_actions_role_arn`, `target_group_arn`,
and `ecr_repository_urls` — note these down for CI configuration.

### 4. Configure GitHub Actions secrets

In your GitHub repo: Settings → Secrets and variables → Actions → New repository secret

| Secret name | Value | Source |
|---|---|---|
| `AWS_ROLE_TO_ASSUME` | ARN from `github_actions_role_arn` output | Terraform output |
| `TARGET_GROUP_ARN` | ARN from `gateway_target_group_arn` output | Terraform output |
| `ALB_DNS` | DNS from `alb_dns_name` output | Terraform output |

Also set these as **Variables** (not secrets):

| Variable | Value |
|---|---|
| `AWS_REGION` | `us-east-1` (or whatever you used) |
| `ECR_REPOS_PREFIX` | `ecom` |
| `AWS_ACCOUNT_ID` | Your 12-digit AWS account ID |

### 5. Push to main → CI/CD takes over

Any push to `main` triggers:
1. **CI** (`.github/workflows/ci.yml`) — runs pytest on all 4 services
2. **Deploy** (`.github/workflows/deploy.yml`):
   - Builds + pushes all 4 Docker images to ECR (parallel matrix)
   - Runs `scripts/deploy_rolling.sh`:
     - Deregisters EC2-1 from ALB
     - SSM Run Command: `docker compose pull && docker compose up -d`
     - Waits for /health to return 200
     - Re-registers EC2-1
     - Repeats for EC2-2

Zero downtime — the ALB always has at least one healthy target serving traffic.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | FastAPI 0.115 | Async-native, OpenAPI docs for free, type-safe |
| ORM | SQLAlchemy 2.0 | Modern typed ORM, well-understood |
| DB | Postgres 16 (RDS) | Industry default; one instance + schemas per service |
| Cache/Rate limit | Redis 7 (ElastiCache) | slowapi storage + future refresh-token blacklist |
| Auth | JWT (HS256) | Stateless — gateway verifies without DB hit |
| Rate limiter | slowapi | Real maintained library, not hand-rolled |
| Inter-service | httpx (async) | Non-blocking calls with retries + timeouts |
| Containers | Docker (multi-stage) | Slim final images, reproducible builds |
| IaC | Terraform 1.7+ | Industry standard, declarative, remote state |
| CI/CD | GitHub Actions + OIDC | No long-lived AWS keys, scoped per-repo |
| Deploy | SSM Run Command | No SSH keys, fully audited, idempotent |
| Load test | Locust | Python-native, matches the stack |

## Test status

All 29 tests pass:

```
services/user-service/        5/5 ✓
services/product-service/     7/7 ✓
services/order-service/       7/7 ✓
services/api-gateway/        10/10 ✓
```

Tests cover the happy path + failure modes (duplicate email, wrong password,
insufficient stock, invalid JWT, rate limit exceeded, routing logic, etc.).
