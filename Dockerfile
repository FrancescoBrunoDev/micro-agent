# syntax=docker/dockerfile:1
# micro-agent — one portable container: herdr + pi + kDrive sync.
# Runs on Coolify or any docker host; no dependency on the developer machine.

FROM node:22-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates jq tini bash openssh-server \
    && rm -rf /var/lib/apt/lists/*

# rclone from rclone.org: bookworm's 1.61 is too old for kDrive WebDAV bisync
# ("modification time support is missing"). Arch-aware for arm64 hosts.
RUN set -eux; \
    case "$(uname -m)" in x86_64) A=amd64 ;; aarch64) A=arm64 ;; *) echo "unsupported arch: $(uname -m)"; exit 1 ;; esac; \
    curl -fsSL "https://downloads.rclone.org/rclone-current-linux-${A}.deb" -o /tmp/rclone.deb \
    && apt-get install -y /tmp/rclone.deb \
    && rm /tmp/rclone.deb \
    && rclone version | head -1 \
    && printf 'Port 22\nPermitRootLogin prohibit-password\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPubkeyAuthentication yes\nAuthorizedKeysFile .ssh/authorized_keys\nHostKey /data/config/ssh/ssh_host_ed25519_key\nPidFile /run/sshd.pid\n' > /etc/ssh/sshd_config

# Pi coding agent (official install: --ignore-scripts, no native build needed)
RUN npm install -g --ignore-scripts --no-audit --no-fund @earendil-works/pi-coding-agent \
    && npm cache clean --force

# Herdr — terminal workspace manager / agent runtime
RUN HERDR_INSTALL_DIR=/usr/local/bin sh -c 'curl -fsSL https://herdr.dev/install.sh | sh' \
    && herdr --version

# All persistent state lives in /data (named volume): pi config+sessions,
# herdr config+socket+layout, rclone config, synced kDrive vault.
ENV HOME=/data/home \
    XDG_CONFIG_HOME=/data/config \
    HERDR_CONFIG_PATH=/data/config/herdr/config.toml \
    PI_CODING_AGENT_DIR=/data/home/.pi/agent \
    SHELL=/bin/bash \
    TERM=xterm-256color

WORKDIR /workspace

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
