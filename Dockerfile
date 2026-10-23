# ------------------------------------------------------------------------------
# Stage 1: Build Dependencies
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Minimal Runtime
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runner

WORKDIR /app

# Install curl for native Docker HEALTHCHECK polling
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user helios (uid=1000, gid=1000)
RUN groupadd -g 1000 helios && \
    useradd -u 1000 -g helios -s /bin/bash -m helios

# Copy Python packages from builder stage
COPY --from=builder --chown=helios:helios /root/.local /home/helios/.local
ENV PATH=/home/helios/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV MEMORY_DATA_DIR=/data

# Create and set permissions on data volume directory
RUN mkdir -p /data/exports /data/exports/changelog && \
    chown -R helios:helios /data /app

# Copy application code
COPY --chown=helios:helios src/ ./src/

USER helios

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]