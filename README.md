# micro-agent

A self-contained **pi-web** Docker deployment for [Pi Coding Agent](https://github.com/earendil-works/pi) browser UI.

No gateway, no Telegram — just the web UI for supervising persistent Pi sessions on your local LLM.

## Quick start

```bash
cp .env.example .env
# Edit .env: set LLM_BASE_URL to your LLM endpoint

docker compose up -d --build
# Open http://localhost:8505
```

## Coolify deployment

1. Import this repo into Coolify
2. Set environment variables:
   - `LLM_BASE_URL` — your OpenAI-compatible LLM endpoint (e.g. `http://ollama:11434/v1`)
   - `PI_MODEL_NAME` — model identifier
   - `OPENAI_API_KEY` — if your LLM requires one
   - `PI_WEB_BIND_ADDR=0.0.0.0` — expose the web UI
3. Deploy

## How it works

- **Single container** runs both pi-web (browser UI) and sessiond (Pi session manager)
- Pi is bundled as an npm peer dependency of `@jmfederico/pi-web` — no separate installation
- `models.json` is generated inside the container from env vars on first start
- All persistent data uses a named Docker volume (`pi-web-data`)

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://host.docker.internal:8080/v1` | OpenAI-compatible LLM endpoint |
| `OPENAI_API_KEY` | `not-needed` | API key for the LLM |
| `PI_PROVIDER` | `openai` | Pi provider name |
| `PI_MODEL_NAME` | `qwen2.5-coder:32b` | Model identifier |
| `PI_WEB_BIND_ADDR` | `127.0.0.1` | Web UI bind address (use `0.0.0.0` for Coolify) |
| `PI_WEB_HOST_PORT` | `8505` | Host port mapped to container's internal 8504 |

See [AGENTS.md](AGENTS.md) for full documentation.
