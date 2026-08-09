#!/bin/bash
set -e

# ─────────────────────────────────────────────────────────────────────
# PI WEB entrypoint — generates Pi's models.json from env vars.
#
# Pi's models.json schema REQUIRES cost to have all four fields:
#   input, output, cacheRead, cacheWrite
# (missing fields → schema error → Pi falls back to built-in OpenAI
#  catalog, which is why the UI shows only OpenAI models).
#
# This script also queries the LLM's /v1/models endpoint and adds the
# served models so your local models appear in the pi-web UI.
# ─────────────────────────────────────────────────────────────────────

MODELS_FILE="${PI_CODING_AGENT_DIR:-/data/home/.pi/agent}/models.json"
mkdir -p "$(dirname "$MODELS_FILE")"

# ── Configure git to use gh as credential helper ──────────────────────
# Lets `git clone/push/pull` use the GH_TOKEN automatically.
git config --global --add safe.directory '*' 2>/dev/null || true
if [ -n "${GH_TOKEN}" ]; then
    git config --global credential.helper '!gh auth git-credential'
    echo "gh credential helper configured (GH_TOKEN present)"
elif command -v gh >/dev/null 2>&1; then
    gh auth status 2>/dev/null && git config --global credential.helper '!gh auth git-credential' \
        && echo "gh credential helper configured (gh auth login)" || echo "gh installed but not authenticated (set GH_TOKEN)"
else
    echo "gh not installed"
fi
if [ -n "${GH_USER_NAME}" ]; then
    git config --global user.name "${GH_USER_NAME}"
fi
if [ -n "${GH_USER_EMAIL}" ]; then
    git config --global user.email "${GH_USER_EMAIL}"
fi

BASE_URL="${OPENAI_BASE_URL:-http://host.docker.internal:8080/v1}"
PROVIDER="${PI_PROVIDER:-llamacpp}"
API_KEY="${LLM_API_KEY:-${OPENAI_API_KEY:-not-needed}}"

# ── Query the LLM server for its model list ─────────────────────────
echo "Querying $BASE_URL/models for available models..."
MODEL_IDS=$(curl -sf -m 10 -H "Authorization: Bearer ${API_KEY}" \
    "${BASE_URL%/}/models" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ids = [m.get('id') for m in d.get('data', []) if m.get('id')]
    for mid in ids:
        print(mid)
except Exception:
    pass
" || true)

if [ -n "$MODEL_IDS" ]; then
    echo "Discovered models:"
    echo "$MODEL_IDS" | sed 's/^/  - /'
    # Build JSON models array
    MODELS_JSON=$(echo "$MODEL_IDS" | python3 -c "
import sys, json
ids = [l.strip() for l in sys.stdin if l.strip()]
models = []
for mid in ids:
    models.append({
        'id': mid,
        'name': mid,
        'input': ['text'],
        'contextWindow': 131072,
        'maxTokens': 8192,
        'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
    })
print(json.dumps(models, indent=2))
")
else
    echo "No models discovered from endpoint; using fallback default model."
    MODELS_JSON='[
      {
        "id": "default",
        "name": "Default Model",
        "input": ["text"],
        "contextWindow": 131072,
        "maxTokens": 8192,
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
      }
    ]'
fi

# Use a distinct provider name (default: llamacpp) so Pi does NOT merge
# its built-in OpenAI catalog (gpt-4, gpt-5, etc.) with our local models.
PROVIDER="${PI_PROVIDER:-llamacpp}"

cat > "$MODELS_FILE" << EOF
{
  "providers": {
    "${PROVIDER}": {
      "baseUrl": "${BASE_URL}",
      "api": "openai-completions",
      "apiKey": "${API_KEY}",
      "compat": {
        "supportsDeveloperRole": false,
        "supportsReasoningEffort": false,
        "supportsUsageInStreaming": false,
        "maxTokensField": "max_tokens"
      },
      "models": ${MODELS_JSON}
    }
  }
}
EOF
echo "models.json written to $MODELS_FILE (baseUrl=${BASE_URL})"

# ── Restrict the model picker to our local provider only ──────────────
# Pi ships with ~38 built-in providers (openai, anthropic, google, ...).
# Without this, the pi-web UI shows all their models too. Setting
# enabledModels in settings.json scopes the picker to our provider.
SETTINGS_FILE="${PI_CODING_AGENT_DIR:-/data/home/.pi/agent}/settings.json"
mkdir -p "$(dirname "$SETTINGS_FILE")"
MODEL_PATTERN="${PI_MODEL_PATTERN:-${PROVIDER}/*}"
if [ -f "$SETTINGS_FILE" ]; then
    python3 - "$SETTINGS_FILE" "$MODEL_PATTERN" << 'PYEOF'
import json, sys
path, pattern = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        settings = json.load(f)
except Exception:
    settings = {}
settings["enabledModels"] = [pattern]
with open(path, "w") as f:
    json.dump(settings, f, indent=2)
print(f"settings.json: enabledModels=[{pattern}]")
PYEOF
else
    cat > "$SETTINGS_FILE" << EOF
{
  "enabledModels": ["${MODEL_PATTERN}"]
}
EOF
    echo "settings.json created: enabledModels=[${MODEL_PATTERN}]"
fi

# ── Mount KDrive via rclone (WebDAV) ────────────────────────────────────
# Requires KDRIVE_URL + KDRIVE_USER + KDRIVE_PASS (app password).
# Mounts at KDRIVE_MOUNT (default /data/kdrive) using FUSE.
if [ -n "${KDRIVE_URL}" ] && [ -n "${KDRIVE_USER}" ] && [ -n "${KDRIVE_PASS}" ]; then
    KDRIVE_MOUNT="${KDRIVE_MOUNT:-/data/kdrive}"
    echo "Mounting KDrive (${KDRIVE_URL}) at ${KDRIVE_MOUNT}..."
    mkdir -p "${KDRIVE_MOUNT}"
    # Configure rclone remote 'kdrive' (webdav backend) from env vars
    RCLONE_CONFIG="/data/config/rclone/rclone.conf"
    mkdir -p "$(dirname "$RCLONE_CONFIG")"
    cat > "$RCLONE_CONFIG" << EOF
[kdrive]
type = webdav
url = ${KDRIVE_URL}
vendor = other
user = ${KDRIVE_USER}
pass = $(rclone obscure "${KDRIVE_PASS}" 2>/dev/null || echo "${KDRIVE_PASS}")
EOF
    export RCLONE_CONFIG="$RCLONE_CONFIG"
    # Mount in background
    rclone mount kdrive: "${KDRIVE_MOUNT}" --allow-other --vfs-cache-mode writes --daemon-timeout 0 &
    # Wait for mount to become ready
    for i in $(seq 1 15); do
        if mountpoint -q "${KDRIVE_MOUNT}" 2>/dev/null || [ -n "$(ls -A "${KDRIVE_MOUNT}" 2>/dev/null)" ]; then
            echo "KDrive mounted at ${KDRIVE_MOUNT}"
            break
        fi
        sleep 1
    done
else
    echo "KDrive not configured (set KDRIVE_URL/KDRIVE_USER/KDRIVE_PASS to enable)"
fi

# ── Start sessiond in the background (manages persistent Pi sessions) ──
echo "Starting pi-web-sessiond..."
pi-web-sessiond &
SESSIOND_PID=$!

# Wait for sessiond socket to be ready
for i in $(seq 1 30); do
    if [ -S /data/pi-web/sessiond.sock ]; then
        echo "sessiond is ready"
        break
    fi
    sleep 1
done

# Start the web server (foreground — this is the main process)
echo "Starting pi-web-server..."
exec pi-web-server
