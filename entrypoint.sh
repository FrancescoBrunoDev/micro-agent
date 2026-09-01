#!/bin/bash
set -euo pipefail

export HOME=/data/home
export XDG_CONFIG_HOME=/data/config
export HERDR_CONFIG_PATH=/data/config/herdr/config.toml
export PI_CODING_AGENT_DIR=/data/home/.pi/agent

mkdir -p "$XDG_CONFIG_HOME/herdr" "$PI_CODING_AGENT_DIR" /data/kdrive

# ── herdr config (first run) ──────────────────────────────────────────────
[ -f "$HERDR_CONFIG_PATH" ] || printf 'onboarding = false\n' > "$HERDR_CONFIG_PATH"

# ── pi config from env: models.json + settings.json ──────────────────────
# models.json schema REQUIRES cost with all four fields
# (input, output, cacheRead, cacheWrite) or pi rejects the whole file.
# settings.json defaultProvider/defaultModel make pi start on the right
# model without an interactive picker.
MODELS_FILE="$PI_CODING_AGENT_DIR/models.json"
SETTINGS_FILE="$PI_CODING_AGENT_DIR/settings.json"
node - "$MODELS_FILE" "$SETTINGS_FILE" <<'NODE'
const fs = require("fs");
const [modelsFile, settingsFile] = process.argv.slice(2);
const baseUrl = (process.env.LLM_BASE_URL || "http://host.docker.internal:8080/v1").replace(/\/+$/, "");
const provider = process.env.PI_PROVIDER || "local";
const apiKey = process.env.LLM_API_KEY || process.env.OPENAI_API_KEY || "not-needed";
const mkModel = (id) => ({
  id, name: id, input: ["text"], contextWindow: 131072, maxTokens: 8192,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
});
(async () => {
  let model = process.env.PI_MODEL_NAME || null;
  if (!model) {
    try {
      const res = await fetch(`${baseUrl}/models`, {
        headers: { Authorization: `Bearer ${apiKey}` },
        signal: AbortSignal.timeout(10000),
      });
      model = (await res.json())?.data?.[0]?.id || null;
    } catch {}
  }
  model ||= "default";
  fs.writeFileSync(modelsFile, JSON.stringify({
    providers: { [provider]: {
      baseUrl, api: "openai-completions", apiKey,
      compat: {
        supportsDeveloperRole: false,
        supportsReasoningEffort: false,
        supportsUsageInStreaming: false,
        maxTokensField: "max_tokens",
      },
      models: [mkModel(model)],
    }},
  }, null, 2));
  let settings = {};
  try { settings = JSON.parse(fs.readFileSync(settingsFile, "utf8")); } catch {}
  settings.defaultProvider = provider;
  settings.defaultModel = model;
  fs.writeFileSync(settingsFile, JSON.stringify(settings, null, 2));
  console.log(`pi configured: provider=${provider} model=${model} baseUrl=${baseUrl}`);
})();
NODE

# ── kDrive (Infomaniak) via rclone WebDAV bisync ──────────────────────────
# The official kDrive client is a Qt GUI app — not runnable headless.
# WebDAV + rclone is Infomaniak's supported server path. No FUSE/caps needed.
VAULT_SUBPATH="${KDRIVE_VAULT_PATH:-Obsidian/Francesco_Vault}"
VAULT_LOCAL="/data/kdrive/$VAULT_SUBPATH"
mkdir -p "$VAULT_LOCAL"

if [ -n "${KDRIVE_URL:-}" ] && [ -n "${KDRIVE_USER:-}" ] && [ -n "${KDRIVE_PASS:-}" ]; then
  export RCLONE_CONFIG=/data/config/rclone/rclone.conf
  mkdir -p "$(dirname "$RCLONE_CONFIG")"
  if [ ! -f "$RCLONE_CONFIG" ]; then
    cat > "$RCLONE_CONFIG" <<EOF
[kdrive]
type = webdav
url = ${KDRIVE_URL}
vendor = other
user = ${KDRIVE_USER}
pass = $(rclone obscure "${KDRIVE_PASS}")
EOF
    chmod 600 "$RCLONE_CONFIG"
  fi
  # ponytail: dumb periodic bisync; on conflict bisync errors and we retry
  # next loop. A persistent conflict needs manual --resync (log will show it).
  (
    first=1
    while true; do
      if [ "$first" = 1 ]; then
        if rclone bisync "kdrive:${VAULT_SUBPATH}" "$VAULT_LOCAL" --resync --create-empty-src-dirs; then
          first=0
          echo "kDrive initial sync done"
        fi
      else
        rclone bisync "kdrive:${VAULT_SUBPATH}" "$VAULT_LOCAL" --create-empty-src-dirs || true
      fi
      sleep "${KDRIVE_SYNC_INTERVAL:-60}"
    done
  ) &
else
  echo "kDrive not configured — vault stays empty (set KDRIVE_URL/KDRIVE_USER/KDRIVE_PASS)"
fi

# ── herdr server + first-run bootstrap ────────────────────────────────────
# Pre-trust the vault dir so pi does not prompt on first run.
mkdir -p "$PI_CODING_AGENT_DIR"
printf '{\n  "%s": true\n}\n' "$VAULT_LOCAL" > "$PI_CODING_AGENT_DIR/trust.json"

herdr server &
HERDR_PID=$!
trap 'kill "$HERDR_PID" 2>/dev/null || true' EXIT TERM INT

for i in $(seq 1 30); do
  herdr status server >/dev/null 2>&1 && break
  sleep 1
done

# First run only: create the vault workspace with a persistent pi pane.
# On later restarts herdr restores the layout from its own session state.
WORKSPACES=$(herdr workspace list 2>/dev/null || echo '{"result":{"workspaces":[]}}')
COUNT=$(printf '%s' "$WORKSPACES" | jq -r '.result.workspaces | length // 0')
if [ "${COUNT:-0}" = "0" ]; then
  herdr integration install pi >/dev/null 2>&1 || true
  CREATED=$(herdr workspace create --cwd "$VAULT_LOCAL" --label vault)
  PANE=$(printf '%s' "$CREATED" | jq -r '.result.root_pane.pane_id // empty')
  if [ -n "$PANE" ]; then
    # -c continues the most recent session: same pane command on restore = resume.
    herdr agent start vault --kind pi --pane "$PANE" --timeout 120000 -- \
      --session-dir "$PI_CODING_AGENT_DIR/sessions/vault" -n vault -c || true
  fi
fi

echo "micro-agent up: herdr server + kDrive sync running. Attach: docker exec -it <container> herdr"
wait "$HERDR_PID"
