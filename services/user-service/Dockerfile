# syntax=docker/dockerfile:1.7

# ---------- builder ----------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps for psycopg2 (though we use psycopg2-binary so this is
# mostly insurance). Keeps the final image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy shared lib + service requirements first for layer caching.
COPY services/shared/ /build/services/shared/
COPY services/user-service/requirements.txt /build/services/user-service/requirements.txt

RUN pip install --no-cache-dir --prefix=/install -r /build/services/user-service/requirements.txt

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# Non-root user — the EC2 host shouldn't run containers as root inside.
RUN groupadd -r app && useradd -r -g app app

WORKDIR /app

# Runtime deps only (no gcc). psycopg2-binary doesn't need libpq, but having
# it doesn't hurt and avoids surprises if someone swaps in plain psycopg2.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY services/shared/ /app/services/shared/
COPY services/user-service/app/ /app/app/

# PYTHONPATH so `services.shared.*` imports work.
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
