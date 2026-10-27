# Multi-stage Dockerfile for sne.space (Easypanel & Coolify compatible)
FROM python:3.11-slim-bookworm

# Install PHP-CLI and system utilities required for dynamic rendering and astronomical libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    php-cli \
    curl \
    git \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The site server is standard-library Python plus php-cli.
# requirements-mcp.txt is for the optional MCP process and is not installed here,
# so a build does not depend on PyPI.

# Copy application files
COPY . /app

# Ensure proper environment variables.
#
# SNE_DATA_DIR points the writable event corpus at the durable volume. Event JSON
# is the only stateful data the service owns; serve/data_paths.py resolves this
# first so a mounted volume always wins over the baked copy.
ENV PYTHONUNBUFFERED=1 \
    OSC_HOST=0.0.0.0 \
    OSC_PORT=8080 \
    PHP_BIN=php \
    SNE_DATA_DIR=/data/astrocats/astrocats/supernovae/output \
    SNE_RUNTIME_DIR=/data/sne-runtime \
    SNE_GIT_REVISION=unknown

# Mutable runtime JSON (recent-events.json, recent-catalog.min.json) lives here so a
# redeploy cannot reset it to the image's build-time copy. Declared as a VOLUME so a
# plain `docker run` keeps the data across container replacement, matching compose.
# Only these two files are mutable; CSS/JS/fonts stay in the image layer.
VOLUME ["/data/sne-runtime"]

# Stamp the build with the commit it came from. Without this there is no way to tell
# which revision is actually deployed: a health check that returns 200 proves *a*
# container is up, not that it is the intended one. Easypanel/Coolify pass no build
# args by default, so the fallback is "unknown" and the running code's git describe
# is reported instead. Override at build time with:
#   docker build --build-arg GIT_REVISION=$(git rev-parse HEAD) .
ARG GIT_REVISION=unknown
LABEL org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.title="sne.space" \
      org.opencontainers.image.description="Open Supernova Catalog server"
# Also make it visible to the running process so /healthz can report it. ARG values
# are not available at runtime, so this is set as a real environment variable.
ENV SNE_GIT_REVISION=${GIT_REVISION}

# Expose HTTP port
EXPOSE 8080

# Health check hits the liveness endpoint, which never touches the catalog, a
# provider, or the SQLite index. The old check used "/" and therefore paid a full
# homepage render on every probe.
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

RUN chmod +x /app/docker-entrypoint.sh

# The entrypoint seeds the data volume on first boot and then execs the server.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python3", "serve/server.py"]
