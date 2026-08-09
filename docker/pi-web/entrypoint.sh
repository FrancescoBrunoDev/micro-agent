#!/bin/bash
set -e

# Generate Pi models.json from environment variables if not already present.
# This allows configuring the LLM endpoint entirely from container env vars
# (no external file mounts needed — perfect for Coolify).
MODELS_FILE="/data/home/.pi/agent/models.json"
mkdir -p "$(dirname "$MODELS_FILE")"

if [ ! -f "$MODELS_FILE" ]; then
    echo "Generating models.json from environment variables..."

    # Default model name
    MODEL_NAME="default"
    PROVIDER="openai"
    BASE_URL="${OPENAI_BASE_URL:-http://host.docker.internal:8080/v1}"
    API_KEY="${OPENAI_API_KEY:-not-needed}"

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
      "models": [
        {
          "id": "${MODEL_NAME}",
          "name": "${MODEL_NAME}",
          "input": ["text"],
          "contextWindow": 131072,
          "maxTokens": 8192,
          "cost": { "input": 0, "output": 0 }
        }
      ]
    }
  }
}
EOF
    echo "models.json generated with provider=${PROVIDER}, model=${MODEL_NAME}"
else
    echo "models.json already exists, skipping generation"
fi

# Hand off to the original command (pi-web-sessiond or pi-web-server)
exec "$@"
