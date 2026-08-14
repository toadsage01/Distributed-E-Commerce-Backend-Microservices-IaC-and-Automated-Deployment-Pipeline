# Architecture

This document captures the key design decisions, trade-offs, and the
"why" behind each choice. Read this if you're asked about the system in
an interview or want to extend it.

## 1. Service decomposition

The system has 4 services, each owning a single bounded context:

| Service | Owns | Doesn't touch |
|---|---|---|
| User Service | User accounts, passwords, JWT issuance, API keys | Products, orders |
| Product Service | Catalog, prices, stock levels | Users, orders |
| Order Service | Orders, order lines, status transitions | User passwords, product stock (calls Product to reserve) |
| API Gateway | Auth verification, rate limiting, request routing | Anything DB-related |

The principle: each service can be replaced or scaled independently
without breaking the others. Order Service doesn't reach into Product's
DB to check stock — it calls Product over HTTP. This is what makes it
genuinely microservices rather than one app split into folders.

## 2. Auth flow

```
1. Client → POST /auth/signup (no auth needed)
   Gateway → User Service: creates user, returns access + refresh JWTs

2. Client → POST /auth/api-keys (with Bearer access token)
   Gateway → User Service: creates API key, returns raw key ONCE

3. Client → GET /products (with X-API-Key + Bearer token)
   Gateway:
     a. Look up API key hash in User Service (cached 60s in-memory)
     b. Verify JWT signature + expiry (no DB call — that's the point of JWT)
     c. Forward request to Product Service with X-User-Id header set

4. Product Service receives request with X-User-Id
   Trusts the header (security group guarantees only the gateway can call it)
```

**Key trade-off**: HS256 JWT signing (single shared secret) vs RS256 (private
key signs, public key verifies). We use HS256 because:
- Single org, single deployment → key distribution is trivial
- One less thing to manage (no key rotation infrastructure)
- For multi-team / multi-tenant: switch to RS256 with private key held
  only by User Service, public key distributed to gateway

**Refresh token rotation**: deliberately simple — refresh tokens are NOT
rotated on use, and there's no Redis blacklist. In real prod:
- Store refresh token JTI in Redis with TTL = refresh token TTL
- Blacklist on logout / password change
- Rotate on every refresh (issue new refresh + invalidate old)

## 3. Rate limiting

- **Library**: slowapi (Starlette-native, backed by `limits` + Redis)
- **Algorithm**: sliding window counter (default in slowapi)
- **Key**: API key, falling back to client IP
- **Limit**: 100 req/min per API key (industry standard for public APIs)
- **Storage**: ElastiCache Redis (so the limit is shared across gateway replicas)

Why key by API key and not IP?
- IPs are cheap to rotate (proxy lists, cellular networks)
- API keys require signup, which raises the cost of abuse
- Per-key limits also enable future tiered pricing (free=100/min, paid=1000/min)

## 4. Database: shared RDS instance, separate schemas per service

```
                    ┌────────────────────────────────┐
                    │   RDS Postgres (one instance)   │
                    │                                │
                    │   Schemas:                     │
                    │     - users    (User Service)  │
                    │     - products (Product Service)│
                    │     - orders   (Order Service)  │
                    └────────────────────────────────┘
```

**The trade-off**: True microservices dogma says one DB instance per service.
We use one shared instance with separate schemas because:

| | One DB per service | Shared DB, separate schemas (chosen) |
|---|---|---|
| Isolation | Full | Schema-level (acceptable) |
| Cost (3 RDS instances) | ~3× more | One instance |
| Cross-service joins | Impossible | Possible (tempting but don't) |
| Backup/restore | Per service | Per DB (atomic) |
| Migration complexity | 3× Alembic chains | One Alembic chain |
| Resume scope | Overkill | Demonstrates the pattern |

If asked: "I'd move to per-service databases when individual services
hit write contention or have different scaling characteristics. For an
MVP, shared-instance-with-schemas gives 80% of the benefit at 30% of the
cost."

## 5. Inter-service communication: synchronous HTTP (httpx)

```
Order Service ──httpx──► User Service (verify user exists)
              ──httpx──► Product Service (fetch price + reserve stock)
```

Why synchronous and not a message queue (Kafka/SQS)?

| | Sync HTTP (chosen) | Async queue |
|---|---|---|
| Latency | +1-5ms per call | +50-500ms per call |
| Failure mode | Caller gets error | Caller doesn't know if it worked |
| Implementation | One library (httpx) | Broker + consumer + DLQ |
| Resume scope | Right-sized | Overkill |
| Real-world fit | Order creation needs instant feedback | Background jobs, notifications, analytics |

For this system, order creation MUST return synchronously (user waits for
"order placed" confirmation). Async would be the right choice for:
- Sending order confirmation emails
- Updating recommendation engine
- Analytics event ingestion

## 6. Zero-downtime deploy

```
ALB ────► EC2-1 (healthy)  ┐
       └► EC2-2 (healthy)  ┘ both serving traffic

Step 1: Deregister EC2-1
ALB ────► [EC2-1 (draining)]  ┐
       └► EC2-2 (healthy)    ┘ all traffic goes to EC2-2

Step 2: Update EC2-1 via SSM Run Command
       (docker compose pull && docker compose up -d)

Step 3: Wait for /health on EC2-1

Step 4: Re-register EC2-1
ALB ────► EC2-1 (healthy again)  ┐
       └► EC2-2 (healthy)         ┘ both serving again

Step 5: Repeat for EC2-2
```

**Why SSM Run Command and not SSH?**
- No SSH keys to manage
- SSM logs every command to CloudTrail (audit trail)
- Works through NAT/firewall (no inbound port 22 needed from internet)
- Same mechanism works for Windows + Linux instances

**Why not blue/green or canary?**
- Blue/green: doubles cost (need 2× instances), more complex routing
- Canary: needs traffic-shifting infrastructure (ALB weighted routing, Istio)
- Rolling: simplest, gets 95% of the benefit. Good enough for resume-scope.

For real prod: canary via ALB weighted target groups. Route 5% to new
version, watch error rate for 5 min, shift to 100% if healthy.

## 7. CI/CD pipeline

```
Pull Request → CI runs (pytest on all 4 services, parallel matrix)
              ↓ (must pass to merge)
Merge to main → Deploy runs:
                ├── Build + push 4 images to ECR (parallel)
                └── Rolling deploy via SSM Run Command (sequential)
                    ├── Deregister EC2-1
                    ├── docker compose pull + up
                    ├── Wait for /health
                    └── Re-register EC2-1
                    (repeat for EC2-2)
```

**Why GitHub OIDC and not AWS access keys?**
- Access keys are long-lived (months/years) → if leaked, big blast radius
- OIDC tokens are short-lived (15 min) → leaked token is useless in 15 min
- No keys to rotate, no secrets in GitHub Actions UI to manage
- Scoped per-repo per-branch (only `main` can deploy)

## 8. Known limitations

Things I'd fix in a real production system:

1. **No Alembic migrations** — tables are auto-created via `Base.metadata.create_all`.
   Fine for dev; prod needs proper migrations with versioned up/down scripts.

2. **No refresh token rotation** — refresh tokens can be reused until they
   expire. Real prod rotates on every use + maintains a Redis blacklist.

3. **No stock release on order failure** — if Product Service reserves
   stock but Order Service's DB write fails, the stock is "leaked". Real
   prod needs a compensating action (release endpoint on Product Service,
   or a Saga pattern with retries).

4. **Single NAT Gateway** — saves ~$30/mo but creates a single point of
   failure for private subnet egress. Prod should have one NAT GW per AZ.

5. **HTTP only** — no HTTPS on the ALB. Real prod needs ACM cert + HTTPS
   listener. Skipped here to avoid requiring a domain name.

6. **All services on one EC2 instance** — true microservices would run
   each service as its own ECS task or k8s pod. We bundle them on EC2
   via docker-compose to keep the IaC simple — a deliberate resume-scope
   trade-off, called out here so it's clear we know the difference.

7. **No metrics / tracing** — no Prometheus, no OpenTelemetry. Real prod
   needs at minimum: RED metrics (Rate, Errors, Duration) per service,
   distributed tracing for cross-service request flow.

8. **Rate-limit counter cache is per-instance** — the 60s API-key cache
   lives in the gateway process. With multiple gateway instances, each
   would cache independently. Real prod should use Redis for this too.

## 9. What would change at "real" production scale

| Trigger | Change |
|---|---|
| >100 RPS | Move from EC2 + docker-compose to ECS Fargate (per-service task counts) |
| >1000 RPS | Per-service RDS instances (split write contention), read replicas |
| >10k RPS | Move to Aurora Serverless v2, add caching layer for hot products |
| Multi-region | Aurora Global Database, Route 53 latency-based routing, regional ECR |
| Strict compliance | KMS-encrypted EBS, VPC Flow Logs, CloudTrail in dedicated account |
| True zero-downtime | Canary deploys via ALB weighted routing + automated rollback on SLO breach |
