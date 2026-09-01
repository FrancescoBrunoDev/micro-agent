# AGENTS.md — micro-agent

## What this is

One portable Docker container: **herdr + pi + kDrive sync**. It runs on Coolify
or any Docker host and is independent of the developer machine. No web UI —
the only exposed port is SSH (22 inside, `${SSH_PORT:-2222}` outside).

```
Docker container (any host)
├── rclone bisync ⇄ kDrive WebDAV (Infomaniak cloud)
│     └── /data/kdrive/Obsidian/Francesco_Vault   (local copy of the vault)
├── herdr server (headless) — owns terminal panes
│     └── workspace "vault" → pane running pi on the vault dir
└── pi (Node.js agent) — sessions in /data/home/.pi/agent/sessions/vault/
```

All persistent state is under `/data` (single named volume). SSH access:
sshd with pubkey auth only (`SSH_PUBLIC_KEY`, port 22, exposed as `${SSH_PORT:-2222}`).

## Entrypoint behavior (`entrypoint.sh`)

1. `herdr/config.toml` with `onboarding = false` (first run)
2. Generates `models.json` + `settings.json` for pi from env (`LLM_BASE_URL`,
   `PI_PROVIDER`, `PI_MODEL_NAME`). `settings.json` sets `defaultProvider` and
   `defaultModel` so pi starts on the right model with no interactive picker.
3. Configures rclone remote `kdrive` (WebDAV) and starts a bisync loop
   (`KDRIVE_SYNC_INTERVAL`, default 60s). First sync is `--resync`.
4. Starts sshd if `SSH_PUBLIC_KEY` is set (host key + authorized_keys in /data).
5. Pre-trusts the vault dir in `trust.json` so pi doesn't prompt.
6. Starts `herdr server`; on first run only, creates workspace `vault` and
   starts `pi -n vault -c` (`--session-dir /data/home/.pi/agent/sessions/vault`)
   in its root pane. Later restarts: herdr restores the layout itself and `-c`
   resumes the most recent pi session.

## Attach & use

```bash
ssh -i ~/.ssh/id_ed25519 -p 2222 root@<container-host>   # then: herdr
# or attach the herdr TUI straight from the desktop:
herdr --remote root@<container-host>  # (ssh port configurable in ~/.ssh/config)
```

Inside the container:

```bash
herdr agent prompt vault "fai X" --wait --timeout 120000
```

The desktop's own kDrive client and Obsidian keep working as before — the
container is just another kDrive client, so edits merge through the cloud.

## Agent profile

Skills and prompts come from `pi-profile/` in this repo (vendored into the
image, copied to `/data/home/.pi/agent/` at every start — the repo is the
source of truth). Excluded on purpose: `omarchy`*, `telegram-bridge`,
`generated-control-surface`, `generative-apps`, `@llblab/pi-telegram`.
Vault-local skills (`endu-api`, `suunto-api`, `utmb-world` in
`Francesco_Vault/.pi/skills/`) arrive automatically through kDrive sync.

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
| `KDRIVE_USER` | — | kDrive login (email) |
| `KDRIVE_PASS` | — | App password |
| `KDRIVE_VAULT_PATH` | `Obsidian/Francesco_Vault` | Vault path relative to kDrive root |
| `KDRIVE_SYNC_INTERVAL` | `60` | Bisync loop interval (seconds) |
| `SSH_PUBLIC_KEY` | — | Authorized key(s) for root login; empty disables sshd |
| `SSH_PORT` | `2222` | Host port mapped to sshd inside the container |

## History

Removed: pi-web, sessiond, Coolify web deployments, the old FastAPI gateway,
FUSE rclone mount. The container above is the whole architecture.
