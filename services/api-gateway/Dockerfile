# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY services/shared/ /build/services/shared/
COPY services/api-gateway/requirements.txt /build/services/api-gateway/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /build/services/api-gateway/requirements.txt

FROM python:3.12-slim AS runtime
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* && apt-get clean
COPY --from=builder /install /usr/local
COPY services/shared/ /app/services/shared/
COPY services/api-gateway/app/ /app/app/
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
