# syntax=docker/dockerfile:1
# PI WEB — web UI for Pi Coding Agent
# Built from npm packages; Pi is resolved as a peer dependency.
# Based on the official pi-web Docker setup (github.com/jmfederico/pi-web).

FROM node:22-bookworm AS builder

# node-pty requires native build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    make g++ python3 git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install pi-web (which pulls Pi as a peer dependency) + Pi directly
# Using the same version pinning approach as the official image
RUN npm install -g --omit=dev --include=peer --no-audit --no-fund \
    "@jmfederico/pi-web@latest" \
    --allow-scripts=node-pty \
  && global_root="$(npm root -g)" \
  && peer_pi_bin="${global_root}/@jmfederico/pi-web/node_modules/.bin/pi" \
  && global_pi_bin="$(npm prefix -g)/bin/pi" \
  && if [ -x "${peer_pi_bin}" ]; then \
       ln -sf "${peer_pi_bin}" "${global_pi_bin}"; \
     elif [ ! -x "${global_pi_bin}" ]; then \
       echo "Could not find pi binary from @earendil-works/pi-coding-agent" >&2; \
       exit 1; \
     fi \
  && npm cache clean --force

FROM node:22-bookworm

# Copy Node.js modules and binaries from builder
COPY --from=builder /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=builder /usr/local/bin /usr/local/bin

# Install tini for proper signal handling (matches official image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Runtime configuration — matches official pi-web Docker compose
ENV HOME=/data/home \
    XDG_CONFIG_HOME=/data/config \
    PI_WEB_HOST=0.0.0.0 \
    PI_WEB_PORT=8504 \
    PI_WEB_DATA_DIR=/data/pi-web \
    PI_WEB_SESSIOND_SOCKET=/data/pi-web/sessiond.sock \
    PI_CODING_AGENT_DIR=/data/pi-agent \
    SHELL=/bin/bash \
    TERM=xterm-256color

WORKDIR /workspace
EXPOSE 8504

ENTRYPOINT ["tini", "--"]
