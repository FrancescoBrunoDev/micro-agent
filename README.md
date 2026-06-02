# micro-agent

**Pi** + thin **gateway** + **Karpathy-style markdown memory**.

Ultra-lightweight agent framework for self-hosted LLMs. Designed to run on machines like Strix Halo, Omarchy, or any local inference server where token overhead matters.

```
curl -fsSL https://pi.dev/install.sh | sh
pip install micro-agent
micro-agent
```

## Why

Most agent frameworks (Hermes, OpenClaw) are heavy — large system prompts, many tools, complex orchestrators. On self-hosted models with limited token throughput (20-30 t/s generation), that overhead means 30+ seconds per turn just on system prompt processing.

**micro-agent** strips this to the bone:

- **Pi** as the agent runtime — minimal system prompt (~200 tokens), just 4 tools
- **Thin gateway** — FastAPI server, ~300 lines, zero bloat
- **Markdown memory** — grep-based retrieval, no vector DB, no infrastructure

## Architecture

```
Telegram / HTTP  ──→  FastAPI Gateway  ──→  Pi RPC (stdin/stdout)
                          ↕                       ↕
                   Markdown Memory           Local LLM
                   (grep-based)              (Ollama/vLLM/llama.cpp)
```

### Components

| Layer | Tech | Size |
|-------|------|------|
| **Agent runtime** | Pi (`pi --mode rpc`) | ~200 token system prompt |
| **Gateway** | FastAPI + asyncio | ~300 lines |
| **Memory** | Markdown files + grep | Zero infrastructure |
| **LLM** | Any OpenAI-compatible endpoint | Your choice |

### Memory System (Karpathy-style)

Memory is stored as plain markdown files with YAML frontmatter:

```
~/.micro-agent/memory/
├── schema.md            # Memory conventions & types
├── index.md             # Full content catalog
├── episodic/            # Conversation facts, events
├── semantic/            # General knowledge, preferences
└── procedural/          # Workflows, how-tos
```

Retrieval is **grep-based** — the fastest possible search. No vector DB, no embedding model, no infrastructure. Just files.

The agent signals memory writes with `MEMORY: <fact to remember>` in its responses. The gateway extracts these and writes them as markdown files.

## Docker

```bash
# Build the image
docker compose build

# Start with default config (LLM at http://host.docker.internal:8080/v1)
docker compose up -d

# Or with a custom LLM endpoint
LLM_BASE_URL=http://strix-halo:8080/v1 \
MICRO_AGENT_MODEL=step-3.7-flash \
docker compose up -d

# With Telegram bot
TELEGRAM_BOT_TOKEN=your-token \
TELEGRAM_WEBHOOK_SECRET=your-secret \
docker compose up -d

# Check logs
docker compose logs -f

# Test it
curl http://localhost:8765/health
curl -X POST http://localhost:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

### Docker volumes

| Path | Purpose |
|------|---------|
| `/data/memory` | Persistent markdown memory |
| `/app/config.yaml` | Mount custom config |
| `/root/.pi/agent/models.json` | Pi provider/model config |
| `/data/sessions` | Pi session files |

### Pi models.json

Pi reads provider configuration from `~/.pi/agent/models.json`. The Docker setup mounts `./models.json` into the container. Edit this file to change LLM endpoints, API formats, or model parameters. See [Pi custom models docs](https://pi.dev/docs/models) for details.

```json
{
  "providers": {
    "openai": {
      "baseUrl": "http://omarchy:1298/v1",
      "api": "openai-completions",
      "apiKey": "not-needed",
      "compat": {
        "supportsDeveloperRole": false,
        "supportsReasoningEffort": false,
        "thinkingFormat": "qwen-chat-template"
      },
      "models": [
        {
          "id": "unsloth-Qwen3.6-35B-A3B-MTP-GGUF",
          "name": "Qwen 3.6 35B A3B (MTP)",
          "reasoning": true,
          "input": ["text", "image"],
          "contextWindow": 262144,
          "maxTokens": 16384,
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
        }
      ]
    }
  }
}
```

> **Important**: Pi defaults to `openai-responses` API which is incompatible with llama.cpp/vLLM/Ollama. Always use `"api": "openai-completions"` for local endpoints. For Qwen MTP thinking models, set `"thinkingFormat": "qwen-chat-template"`.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_BASE_URL` | `http://host.docker.internal:8080/v1` | LLM API endpoint |
| `OPENAI_API_KEY` | `not-needed` | API key (optional) |
| `MICRO_AGENT_MODEL` | (empty → Pi default) | Model name |
| `MICRO_AGENT_PROVIDER` | `openai` | Provider name |
| `MICRO_AGENT_MEMORY_PATH` | `/data/memory` | Memory directory |
| `TELEGRAM_BOT_TOKEN` | (empty) | Telegram bot token |
| `TELEGRAM_WEBHOOK_SECRET` | (empty) | Webhook secret |

## Quickstart

### 1. Install Pi

```bash
curl -fsSL https://pi.dev/install.sh | sh
# or
npm install -g @earendil-works/pi-coding-agent
```

### 2. Install micro-agent

```bash
pip install micro-agent
```

Or from source:

```bash
git clone https://github.com/FrancescoBrunoDev/micro-agent
cd micro-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Configure

```bash
# Point to your local LLM
export MICRO_AGENT_PROVIDER=openai
export MICRO_AGENT_MODEL=step-3.7-flash

# Or use a config file
cp config.yaml ~/.micro-agent/config.yaml
# Edit ~/.micro-agent/config.yaml with your settings
```

### 4. Run

```bash
# Initialize memory
micro-agent --init-memory

# Start the gateway
micro-agent

# Or with custom port
micro-agent --port 8765 --host 0.0.0.0
```

### 5. Chat

```bash
curl -X POST http://localhost:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello! Who am I speaking with?"}'
```

Or stream:

```bash
curl -X POST http://localhost:8765/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Write a Python script to fetch my IP"}'
```

## Telegram Bot

```bash
# Set up webhook
micro-agent --set-webhook https://your-domain.com/webhook/telegram

# Environment variables:
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_WEBHOOK_SECRET="your-secret"
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/chat` | Send message, get response |
| `POST` | `/chat/stream` | Send message, stream response (SSE) |
| `POST` | `/webhook/telegram` | Telegram bot webhook |
| `POST` | `/memory` | Add memory entry |
| `GET` | `/memory/search?q=query` | Search memory |
| `GET` | `/memory` | List all memory |
| `GET` | `/stats` | Gateway statistics |

## Model Providers

Configure Pi via `models.json` (recommended) or environment variables.

### models.json (recommended)

Edit `./models.json` and mount it into the container (Docker) or place it at `~/.pi/agent/models.json` (local). This gives full control over:
- **API format**: `openai-completions` for llama.cpp/vLLM/Ollama, `openai-responses` for OpenAI
- **Thinking format**: `qwen-chat-template` for Qwen MTP, `deepseek` for DeepSeek-R1
- **Compat flags**: `supportsDeveloperRole`, `maxTokensField`, etc.

The repo ships with a working `models.json` configured for Omarchy (llama.cpp).

### Environment variables

For quick overrides, use env vars:

```bash
export MICRO_AGENT_PROVIDER=openai
export MICRO_AGENT_MODEL=step-3.7-flash
export OPENAI_BASE_URL=http://localhost:8080/v1
```

> **Note**: `OPENAI_BASE_URL` sets the endpoint in docker-compose but Pi requires `models.json` for full control over API format and thinking compatibility. If you only set env vars without `models.json`, Pi will default to `openai-responses` API which doesn't work with most local endpoints.

## Why not OpenClaw?

OpenClaw is Pi + a full gateway — but it adds complexity: SOUL.md/MEMORY.md, session management, skill system, WebSocket protocol. If you need all that, use OpenClaw.

If you want the **minimum viable agent** that's fast on self-hosted models, with transparent markdown memory you can browse in Obsidian — use micro-agent.

| | micro-agent | OpenClaw |
|---|---|---|
| System prompt | ~200 tokens | Pi base + gateway overhead |
| Memory | Markdown + grep (zero infra) | SOUL.md/MEMORY.md |
| Gateway code | ~300 lines Python | 50K+ lines TypeScript |
| Memory visibility | Open in Obsidian | CLI commands |
| Dependencies | FastAPI + subprocess | Full OpenClaw stack |

## License

MIT
