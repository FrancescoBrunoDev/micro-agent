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

BASE_URL="${OPENAI_BASE_URL:-http://host.docker.internal:8080/v1}"
PROVIDER="${PI_PROVIDER:-llamacpp}"
API_KEY="${OPENAI_API_KEY:-not-needed}"

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
