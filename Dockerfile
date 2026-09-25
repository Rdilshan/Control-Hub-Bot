# Multi-stage production Dockerfile for Control Hub
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt


# Final Runtime Stage
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/controlhub/.local/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and group
RUN groupadd -g 10001 controlhub && \
    useradd -u 10001 -g controlhub -m -s /bin/bash controlhub && \
    mkdir -p /tmp/controlhub && \
    chown -R controlhub:controlhub /tmp/controlhub /app

# Copy installed python packages from builder
COPY --from=builder --chown=controlhub:controlhub /root/.local /home/controlhub/.local

# Copy application source
COPY --chown=controlhub:controlhub . /app

USER controlhub

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
