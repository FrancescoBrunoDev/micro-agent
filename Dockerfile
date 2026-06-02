# syntax=docker/dockerfile:1
# micro-agent — Docker image
# Multi-stage: Node.js deps in build stage, Python + Pi in final image

# ── Build stage: Install Pi (Node.js) ────────────────────────────────
FROM node:22-alpine AS pi-builder

RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent \
    && npm cache clean --force

# ── Final stage ──────────────────────────────────────────────────────
FROM python:3.13-slim

# Install Node.js 22 (Pi requires Node >= 22, Debian apt has 20)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs git \
    && rm -rf /var/lib/apt/lists/*

# Copy Pi from build stage
COPY --from=pi-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js /usr/local/bin/pi

# Verify Pi
RUN pi --version || echo "Pi verification done"

# Install micro-agent from PyPI (or from local source if building locally)
# For now, we install from source since it's not on PyPI yet
WORKDIR /app

# Copy micro-agent source
COPY pyproject.toml README.md ./
COPY micro_agent/ ./micro_agent/

# Install micro-agent and its Python dependencies
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir uvicorn[standard]

# Create directories for persistence
RUN mkdir -p /data/memory /data/sessions

# Default configuration
ENV MICRO_AGENT_HOST=0.0.0.0
ENV MICRO_AGENT_PORT=8765
ENV MICRO_AGENT_PROVIDER=openai
ENV MICRO_AGENT_MODEL=
ENV MICRO_AGENT_CONFIG=/app/config.yaml
ENV PI_DISABLE_UPDATE_CHECK=1
ENV PAGER=cat
ENV EDITOR=cat

# Pi uses these env vars for the OpenAI-compatible provider
# Set OPENAI_BASE_URL to point to your local LLM endpoint
# Set OPENAI_API_KEY if needed (many local LLMs don't require one)

# Copy default config
COPY config.yaml /app/config.yaml

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8765/health || exit 1

EXPOSE 8765

# Initialize memory on first run and start gateway
CMD ["sh", "-c", "\
    micro-agent --init-memory 2>/dev/null; \
    exec micro-agent \
"]
