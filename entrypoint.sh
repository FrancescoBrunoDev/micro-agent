#!/bin/bash
set -euo pipefail

export HOME=/data/home
export XDG_CONFIG_HOME=/data/config
export HERDR_CONFIG_PATH=/data/config/herdr/config.toml
export PI_CODING_AGENT_DIR=/data/home/.pi/agent

mkdir -p "$XDG_CONFIG_HOME/herdr" "$PI_CODING_AGENT_DIR" /data/kdrive

# ── herdr config (first run) ──────────────────────────────────────────────
[ -f "$HERDR_CONFIG_PATH" ] || printf 'onboarding = false\n' > "$HERDR_CONFIG_PATH"

# ── git/gh: token auth + identity ─────────────────────────────────────────
# gh uses GH_TOKEN as its login automatically; teach git to go through it.
git config --global --add safe.directory '*' 2>/dev/null || true
if [ -n "${GH_TOKEN:-}" ]; then
  git config --global credential.helper '!gh auth git-credential'
  echo "gh authenticated via GH_TOKEN"
fi
[ -n "${GH_USER_NAME:-}" ] && git config --global user.name "$GH_USER_NAME"
[ -n "${GH_USER_EMAIL:-}" ] && git config --global user.email "$GH_USER_EMAIL"

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
const baseUrl = (process.env.LLAMACPP_BASE_URL || "http://host.docker.internal:8080/v1").replace(/\/+$/, "");
const provider = "llamacpp";
const apiKey = process.env.LLAMACPP_API_KEY || "not-needed";
const mkModel = (id) => ({
  id, name: id, input: ["text"], contextWindow: 131072, maxTokens: 8192,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
});
(async () => {
  // Discover served models from llama.cpp; pi never needs a hardcoded model id.
  let models = null;
  try {
    const res = await fetch(`${baseUrl}/models`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(10000),
    });
    const ids = ((await res.json())?.data || []).map((m) => m.id).filter(Boolean);
    if (ids.length) models = ids.map(mkModel);
  } catch {}
  models ||= [mkModel("default")];
  fs.writeFileSync(modelsFile, JSON.stringify({
    providers: { [provider]: {
      baseUrl, api: "openai-completions", apiKey,
      compat: {
        supportsDeveloperRole: false,
        supportsReasoningEffort: false,
        supportsUsageInStreaming: false,
        maxTokensField: "max_tokens",
      },
      models,
    }},
  }, null, 2));
  let settings = {};
  try { settings = JSON.parse(fs.readFileSync(settingsFile, "utf8")); } catch {}
  settings.defaultProvider = provider;
  // Only pick a default once; afterwards pi's own choice is preserved.
  if (!settings.defaultModel) settings.defaultModel = models[0].id;
  // pi installs these at startup into ~/.pi/agent/npm and ~/.pi/agent/git.
  // Excluded on purpose: @llblab/pi-telegram (telegram bridge).
  settings.packages = [
    "npm:pi-docparser",
    "npm:pi-observability",
    "npm:@juicesharp/rpiv-web-tools",
    "git:github.com/DietrichGebert/ponytail",
  ];
  fs.writeFileSync(settingsFile, JSON.stringify(settings, null, 2));
  console.log(`pi configured: provider=${provider} models=${models.map((m) => m.id).join(",")} baseUrl=${baseUrl}`);
})();
NODE

# ── agent profile: vendored skills + prompts (omarchy & telegram excluded) ──
# rm -rf first: a previous deploy left broken symlinks, and cp cannot
# replace a non-directory with a directory. Repo is the source of truth.
rm -rf "$PI_CODING_AGENT_DIR/skills" "$PI_CODING_AGENT_DIR/prompts"
mkdir -p "$PI_CODING_AGENT_DIR/skills" "$PI_CODING_AGENT_DIR/prompts"
cp -r /opt/pi-profile/skills/. "$PI_CODING_AGENT_DIR/skills/"
cp -r /opt/pi-profile/prompts/. "$PI_CODING_AGENT_DIR/prompts/"

# ── kDrive (Infomaniak) via rclone WebDAV bisync ──────────────────────────
# The official kDrive client is a Qt GUI app — not runnable headless.
# WebDAV + rclone is Infomaniak's supported server path. No FUSE/caps needed.
VAULT_SUBPATH="${KDRIVE_VAULT_PATH:-Obsidian/Francesco_Vault}"
VAULT_LOCAL="/data/kdrive/$VAULT_SUBPATH"
mkdir -p "$VAULT_LOCAL"

if [ -n "${KDRIVE_URL:-}" ] && [ -n "${KDRIVE_USER:-}" ] && [ -n "${KDRIVE_PASS:-}" ]; then
  export RCLONE_CONFIG=/data/config/rclone/rclone.conf
  mkdir -p "$(dirname "$RCLONE_CONFIG")"
  # Rewritten every start so env changes (e.g. rotated password) take effect.
  cat > "$RCLONE_CONFIG" <<EOF
[kdrive]
type = webdav
url = ${KDRIVE_URL}
vendor = owncloud
user = ${KDRIVE_USER}
pass = $(rclone obscure "${KDRIVE_PASS}")
EOF
  chmod 600 "$RCLONE_CONFIG"
  # ponytail: dumb periodic bisync; on conflict bisync errors and we retry
  # next loop. A persistent conflict needs manual --resync (log will show it).
  # Stale lock files from crashed runs would block bisync forever: drop them
  # at startup (we are the only bisync writer in this container).
  rm -f /data/home/.cache/rclone/bisync/*.lck
  (
    first=1
    while true; do
      if [ "$first" = 1 ]; then
        if rclone bisync "kdrive:${VAULT_SUBPATH}" "$VAULT_LOCAL" --resync; then
          first=0
          echo "kDrive initial sync done"
        fi
      else
        rclone bisync "kdrive:${VAULT_SUBPATH}" "$VAULT_LOCAL" || true
      fi
      sleep "${KDRIVE_SYNC_INTERVAL:-60}"
    done
  ) &
else
  echo "kDrive not configured — vault stays empty (set KDRIVE_URL/KDRIVE_USER/KDRIVE_PASS)"
fi

# ── sshd (pubkey auth from env, no passwords) ───────────────────────────
if [ -n "${SSH_PUBLIC_KEY:-}" ]; then
  mkdir -p /data/home/.ssh /data/config/ssh /run/sshd
  printf '%s\n' "$SSH_PUBLIC_KEY" > /data/home/.ssh/authorized_keys
  chmod 700 /data/home/.ssh && chmod 600 /data/home/.ssh/authorized_keys
  [ -f /data/config/ssh/ssh_host_ed25519_key ] || \
    ssh-keygen -t ed25519 -N '' -q -f /data/config/ssh/ssh_host_ed25519_key
  /usr/sbin/sshd -f /etc/ssh/sshd_config
  echo "sshd listening on port 22"
else
  echo "SSH disabled (set SSH_PUBLIC_KEY to enable)"
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
# On later restarts herdr restores the layout from its own session state;
# this guard is idempotent on the label so it also self-heals after a
# broken restore. Panes get explicit env because herdr/spawned shells
# derive HOME from passwd, not from the server environment.
VAULT_WS=$(herdr workspace list 2>/dev/null | jq -r '[.result.workspaces[] | select(.label == "vault")] | length')
if [ "${VAULT_WS:-0}" = "0" ]; then
  herdr integration install pi >/dev/null 2>&1 || true
  CREATED=$(herdr workspace create --cwd "$VAULT_LOCAL" --label vault \
    --env HOME=/data/home --env PI_CODING_AGENT_DIR=/data/home/.pi/agent)
  PANE=$(printf '%s' "$CREATED" | jq -r '.result.root_pane.pane_id // empty')
  if [ -n "$PANE" ]; then
    # -c continues the most recent session: same pane command on restore = resume.
    herdr agent start vault --kind pi --pane "$PANE" --timeout 120000 -- \
      --session-dir "$PI_CODING_AGENT_DIR/sessions/vault" -n vault -c || true
  fi
fi

echo "micro-agent up: herdr server + kDrive sync running. Attach: docker exec -it <container> herdr"
wait "$HERDR_PID"
