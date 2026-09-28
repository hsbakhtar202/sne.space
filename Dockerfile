# Multi-stage Dockerfile for sne.space (Easypanel & Coolify compatible)
FROM python:3.11-slim-bookworm

# Install PHP-CLI and system utilities required for dynamic rendering and astronomical libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    php-cli \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The site server is standard-library Python plus php-cli.
# requirements-mcp.txt is for the optional MCP process and is not installed here,
# so a build does not depend on PyPI.

# Copy application files
COPY . /app

# Ensure proper environment variables
ENV PYTHONUNBUFFERED=1 \
    OSC_HOST=0.0.0.0 \
    OSC_PORT=8080 \
    PHP_BIN=php

# Expose HTTP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/ || exit 1

# Start the high-performance threaded Python server
CMD ["python3", "serve/server.py"]
