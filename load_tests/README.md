# Load Testing

Locust-based load tests against the API gateway. Goal: hit 500 concurrent
users and measure end-to-end latency + RPS through the full microservices
path (gateway → JWT verify → rate limit → downstream → DB).

## Setup

```bash
# Install locust
pip install -r requirements.txt

# Make sure the stack is running (either locally or via ALB)
docker compose up --build -d   # local

# OR set LOADTEST_HOST to your ALB DNS:
export LOADTEST_HOST=http://<ALB_DNS>
```

## Run

### Web UI (interactive, great for exploratory testing)

```bash
locust -f locustfile.py --host=http://localhost:8000
```

Open http://localhost:8089 in your browser → enter 500 users, 8 spawn rate.

### Headless (for CI + reproducible numbers)

```bash
locust -f locustfile.py \
    --host=http://localhost:8000 \
    --headless \
    -u 500 \
    -r 8 \
    -t 300s \
    --html=report.html \
    --csv=report
```

This runs 500 concurrent users, ramping up 8/sec, for 5 minutes. Output:
- `report.html` — interactive HTML report
- `report_stats.csv` — per-request stats
- `report_failures.csv` — failure breakdown

## What it tests

The test creates one user + one API key at startup (shared across all
locust workers), then each worker simulates a real client making:

| Endpoint            | Weight | Why |
|--------------------|-------|------|
| GET /products      | 40%   | Catalog browsing — most common in real e-commerce |
| GET /products/:id  | 30%   | Product detail pages |
| GET /orders        | 15%   | Order history |
| POST /orders       | 10%   | Place order — exercises the full Order → User → Product inter-service path |
| GET /users/me      | 5%    | Profile page |

## Expected results (with docker-compose on a laptop)

| Metric      | Expectation |
|------------|-------------|
| RPS         | 200–400     |
| P50 latency | 50–150ms    |
| P95 latency | 200–500ms   |
| P99 latency | 500–1500ms  |
| Error rate  | <1% (some 404s on random product IDs are expected) |

If your numbers are much worse:
- Check RDS Postgres CPU + connection count
- Check ElastiCache Redis hit rate (should be >99% on rate-limit checks)
- Check the gateway's CPU — if it's at 100%, scale horizontally (more EC2)
- Check that the inter-service httpx calls aren't waiting on connection pool

## Output report

After a run, commit `report.html` to the repo as your load-test evidence.
This is the number that goes on your resume: "designed and load-tested
a microservices backend handling 500 concurrent users at ~X RPS with
P95 latency of Yms".
