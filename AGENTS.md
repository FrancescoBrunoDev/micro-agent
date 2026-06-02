# AGENTS.md — micro-agent

Instructions for AI coding agents working on this codebase.

## What is this?

micro-agent is a thin FastAPI gateway that wraps **Pi** (a Node.js coding agent CLI) in RPC mode, with markdown-based persistent memory. It's designed for self-hosted LLMs (llama.cpp, vLLM, Ollama).

```
User (HTTP/Telegram) → FastAPI Gateway → Pi RPC (stdin/stdout) → Local LLM
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
  providers.py     Telegram provider
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
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` — optional Telegram bot
