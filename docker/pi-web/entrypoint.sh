#!/bin/bash
set -e

# Generate Pi models.json from environment variables if not already present.
MODELS_FILE="/data/home/.pi/agent/models.json"
mkdir -p "$(dirname "$MODELS_FILE")"

if [ ! -f "$MODELS_FILE" ]; then
    echo "Generating models.json from LLM_BASE_URL env var..."

    BASE_URL="${OPENAI_BASE_URL:-http://host.docker.internal:8080/v1}"
    API_KEY="${OPENAI_API_KEY:-not-needed}"

    cat > "$MODELS_FILE" << EOF
{
  "providers": {
    "openai": {
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
          "id": "default",
          "name": "Default Model (select in pi-web UI)",
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
    echo "models.json generated with baseUrl=${BASE_URL}"
else
    echo "models.json already exists, skipping generation"
fi

# Start sessiond in the background (manages persistent Pi sessions)
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
