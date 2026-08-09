# AGENTS.md — micro-agent

Instructions for AI coding agents working on this codebase.

## What is this?

micro-agent is a thin FastAPI gateway that wraps **Pi** (a Node.js coding agent CLI) in RPC mode, with markdown-based persistent memory. It's designed for self-hosted LLMs (llama.cpp, vLLM, Ollama).

```
User (HTTP) → FastAPI Gateway → Pi RPC (stdin/stdout) → Local LLM
                              ↕                    ↕
                       Markdown Memory         Pi (Node.js)
                       (~/.micro-agent/)
```

## Project layout

```
micro_agent/
  main.py          FastAPI app + CLI entry point
  gateway.py       Core orchestration: prompt building, event streaming, memory
  pi_client.py     Pi subprocess manager (stdin/stdout JSONL)
  models.py        Pydantic config models
  memory.py        Markdown file store (grep-based retrieval)
config.yaml        Default gateway config
models.json        Pi provider/model config (mounted into container)
docker-compose.yml Docker service definition
Dockerfile         Multi-stage: Node.js Pi + Python gateway
pyproject.toml     Python package metadata
.env               Docker environment template
```

## Build & run

```bash
# Build
docker compose build

# Run (set LLM endpoint + model)
LLM_BASE_URL=http://your-llm:port/v1 \
MICRO_AGENT_MODEL=your-model-id \
docker compose up -d

# Test
curl http://localhost:8765/health
curl -X POST http://localhost:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

## Key architecture decisions

### Pi via RPC (JSONL over stdin/stdout)

- Pi runs as `pi --mode rpc --provider openai --model <name> --no-session`
- Gateway sends JSON lines to stdin, reads JSON lines from stdout
- `pi_client.py` uses `asyncio.create_subprocess_exec` — **do not** reintroduce `connect_read_pipe` or manual StreamReader wrapping; it breaks with uvloop
- The `_drain_stderr` background task prevents stderr buffer deadlocks

### Pi models.json

- Pi reads provider config from `~/.pi/agent/models.json`
- Pi defaults to `openai-responses` API which is **incompatible** with llama.cpp/vLLM/Ollama
- Must use `"api": "openai-completions"` for local endpoints
- For Qwen MTP models: `"thinkingFormat": "qwen-chat-template"`
- This file is mounted into the Docker container at `/root/.pi/agent/models.json`

### Event handling

- Pi emits events: `agent_start`, `turn_start`, `message_start`, `message_update` (deltas), `message_end`, `turn_end`, `agent_end`
- `message_update` events use `assistantMessageEvent` envelope with `type: "text_delta"` and `delta` field
- `message_end` events carry the full `message` object with `role`, `content[]`, `api`, etc.
- User messages have `message_end` with `role: "user"` — **do not** treat these as final output
- Assistant messages have `message_end` with `role: "assistant"` and `content[]` blocks

### Docker build gotchas

- **Node.js version**: Pi requires Node ≥ 22. `python:3.13-slim` apt has Node 20. Must install from NodeSource.
- **Pi binary path**: Pi 0.78+ uses `dist/cli.js`, not `bin/cli.js`
- **setuptools backend**: Must use `setuptools.build_meta`, not `setuptools.backends._legacy._Backend`

## Common pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: micro_agent.cli` | pyproject entry point wrong | Set to `micro_agent.main:main` |
| `Pi binary not found` | Wrong symlink path | `dist/cli.js` not `bin/cli.js` |
| Empty LLM responses | Wrong API format | `models.json` with `api: openai-completions` |
| `Connection reset by peer` | uvloop + connect_read_pipe | Use process stdout/stdin directly |
| Pi exits code 1 immediately | Node.js version mismatch | Install Node 22 via NodeSource |
| Container keeps restarting | Entry point crash | Check `docker compose logs` |

## Environment variables

All in `.env` (read by docker-compose):

- `LLM_BASE_URL` → `OPENAI_BASE_URL` in container
- `OPENAI_API_KEY` — set to `not-needed` for local LLMs
- `MICRO_AGENT_MODEL` — model ID
- `MICRO_AGENT_PROVIDER` — provider name (default: `openai`)

## PI WEB (browser UI for Pi Coding Agent)

This project runs [pi-web](https://pi-web.dev/) as a Docker Compose service. Since pi-web bundles Pi as an npm peer dependency, there is no separate gateway — just the browser UI.

### Coolify deployment

1. Import this repo into Coolify
2. Set environment variables (see `.env.example`):
   - `LLM_BASE_URL` — your LLM endpoint (e.g. `http://ollama:11434/v1`)
   - `PI_MODEL_NAME` — model identifier
   - `OPENAI_API_KEY` — if your LLM requires one
3. Set `PI_WEB_BIND_ADDR=0.0.0.0` to expose the web UI
4. Deploy

### Local deployment

```bash
cp .env.example .env
# Edit .env...
docker compose up -d --build
# Open http://localhost:8504
```

### How it works

- **No external file mounts** — `models.json` is generated inside the container from env vars (`OPENAI_BASE_URL`, `PI_PROVIDER`, `PI_MODEL_NAME`) on first start
- **Named volumes** — all persistent data (sessions, workspaces, Pi config) uses a Docker named volume (`pi-web-data` by default), configurable via `PI_WEB_VOLUME_NAME`
- **Pi is bundled** — installed as an npm peer dependency of `@jmfederico/pi-web`, no separate installation needed

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://host.docker.internal:8080/v1` | OpenAI-compatible LLM endpoint |
| `OPENAI_API_KEY` | `not-needed` | API key for the LLM |
| `PI_PROVIDER` | `openai` | Pi provider name |
| `PI_MODEL_NAME` | `qwen2.5-coder:32b` | Model identifier (used in models.json) |
| `PI_WEB_BIND_ADDR` | `127.0.0.1` | Web UI bind address (use `0.0.0.0` for Coolify) |
| `PI_WEB_HOST_PORT` | `8504` | Web UI port |
| `PI_WEB_VOLUME_NAME` | `pi-web-data` | Named volume for persistent data |

### How models are discovered

On startup, `entrypoint.sh`:

1. Reads `LLM_BASE_URL` from the environment (this is the OpenAI-compatible endpoint, e.g. llama.cpp)
2. Queries `{LLM_BASE_URL}/models` to discover the served models automatically
3. Writes a valid `models.json` to `$PI_CODING_AGENT_DIR` (default `/data/pi-agent`) — this is the directory pi-web's Pi processes actually use
4. Models appear in the pi-web UI under the provider name `llamacpp` (configurable via `PI_PROVIDER`)

**Important schema detail:** Pi's `models.json` requires every model's `cost` object to have ALL FOUR fields — `input`, `output`, `cacheRead`, `cacheWrite`. If any are missing, the entire file is rejected and Pi falls back to its built-in OpenAI catalog (showing only gpt-* models). The entrypoint always generates all four.

**Why a custom provider name?** Using `llamacpp` (instead of `openai`) prevents Pi from merging its built-in OpenAI catalog (gpt-4, gpt-5, etc.) into your local config. Your local models appear cleanly under the `llamacpp` provider in the UI.

**Why only my models show (no gpt-\*)?** Pi ships with ~38 built-in providers. A provider only appears in the UI if it's "configured" (has credentials). The `openai` provider becomes configured when `OPENAI_API_KEY` is set as a container env var — so we deliberately do NOT pass it globally. The API key lives only inside `models.json` (per-provider), keeping the built-in OpenAI catalog hidden.

### Networking (Coolify / Raspberry Pi)

The container has a stable hostname (`pi-web`), so on the Docker network:

- **Other services on the same network** reach pi-web at `http://pi-web:8504`
- **pi-web reaches other services** by their hostnames (e.g. `http://my-llm:8080/v1`)
- **Services on the host itself** (e.g. llama.cpp running directly on the Pi) are
  reachable at `http://host.docker.internal:<port>` (via `extra_hosts: host-gateway`)

On Coolify, the application is automatically attached to the `coolify` network, so
pi-web can reach other Coolify apps by their internal hostnames and vice versa.
For tailnet/LAN hosts that Docker DNS can't resolve (e.g. `raspberrypi2` via
Tailscale), add the mapping in Coolify UI → container settings → **Extra Hosts**,
e.g. `raspberrypi2:100.98.224.117`.

Externally, pi-web is reachable at `http://<pi-ip>:8505` (0.0.0.0 binding).

### Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Runs the single `pi-web` service (sessiond + web in one container) |
| `docker/pi-web/Dockerfile` | Builds the pi-web image (Node.js 22, includes Pi) |
| `docker/pi-web/entrypoint.sh` | Discovers models + generates models.json, starts sessiond + web |
