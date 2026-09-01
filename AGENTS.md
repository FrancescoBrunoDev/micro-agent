# AGENTS.md — micro-agent

## What this is

One portable Docker container: **herdr + pi + kDrive sync**. It runs on Coolify
or any Docker host and is independent of the developer machine. No web UI, no
ports — the container is an agent host you attach to.

```
Docker container (any host)
├── rclone bisync ⇄ kDrive WebDAV (Infomaniak cloud)
│     └── /data/kdrive/Obsidian/Francesco_Vault   (local copy of the vault)
├── herdr server (headless) — owns terminal panes
│     └── workspace "vault" → pane running pi on the vault dir
└── pi (Node.js agent) — sessions in /data/home/.pi/agent/sessions/vault/
```

All persistent state is under `/data` (single named volume).

## Entrypoint behavior (`entrypoint.sh`)

1. `herdr/config.toml` with `onboarding = false` (first run)
2. Generates `models.json` + `settings.json` for pi from env (`LLM_BASE_URL`,
   `PI_PROVIDER`, `PI_MODEL_NAME`). `settings.json` sets `defaultProvider` and
   `defaultModel` so pi starts on the right model with no interactive picker.
3. Configures rclone remote `kdrive` (WebDAV) and starts a bisync loop
   (`KDRIVE_SYNC_INTERVAL`, default 60s). First sync is `--resync`.
4. Pre-trusts the vault dir in `trust.json` so pi doesn't prompt.
5. Starts `herdr server`; on first run only, creates workspace `vault` and
   starts `pi -n vault -c` (`--session-dir /data/home/.pi/agent/sessions/vault`)
   in its root pane. Later restarts: herdr restores the layout itself and `-c`
   resumes the most recent pi session.

## Attach & use

```bash
docker exec -it micro-agent herdr                 # TUI: see panes, agents
docker exec -it micro-agent herdr agent prompt vault "fai X" --wait --timeout 120000
```

The desktop's own kDrive client and Obsidian keep working as before — the
container is just another kDrive client, so edits merge through the cloud.

## Pitfalls

- **models.json schema**: `cost` must have ALL FOUR fields — `input`, `output`,
  `cacheRead`, `cacheWrite` — or pi rejects the file and falls back to its
  built-in OpenAI catalog.
- **API format**: local LLMs (llama.cpp/vLLM/Ollama) need `api: openai-completions`
  (default `openai-responses` is incompatible).
- **kDrive client is GUI-only**: the official client has no headless mode.
  rclone over WebDAV is the supported server path. No FUSE/caps needed since
  we bisync instead of mount.
- **bisync conflicts**: on conflict bisync errors and retries next loop; a
  persistent conflict needs a manual `--resync` (rclone config at
  `/data/config/rclone/rclone.conf`).
- **herdr**: do not run bare `herdr` inside a pane (nested launch is blocked);
  use `herdr server` / `herdr agent ...` commands.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://host.docker.internal:8080/v1` | OpenAI-compatible LLM endpoint |
| `LLM_API_KEY` | `not-needed` | API key for the LLM |
| `PI_PROVIDER` | `local` | Provider name in pi's models.json |
| `PI_MODEL_NAME` | (first from /models) | Model id |
| `KDRIVE_URL` | — | WebDAV endpoint `https://<id>.connect.kdrive.infomaniak.com` |
| `KDRIVE_USER` | — | kDrive login (app password) |
| `KDRIVE_PASS` | — | App password |
| `KDRIVE_VAULT_PATH` | `Obsidian/Francesco_Vault` | Vault path relative to kDrive root |
| `KDRIVE_SYNC_INTERVAL` | `60` | Bisync loop interval (seconds) |

## History

Removed: pi-web, sessiond, Coolify web deployments, the old FastAPI gateway,
FUSE rclone mount. The container above is the whole architecture.
