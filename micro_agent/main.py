"""FastAPI entry point and CLI for micro-agent.

The gateway exposes:
- POST /chat — Chat with the agent
- POST /webhook/telegram — Telegram bot webhook
- GET /health — Health check
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from micro_agent.gateway import Gateway
from micro_agent.models import ChatRequest, Config

log = logging.getLogger(__name__)

# Global gateway instance
_gateway: Gateway | None = None


def load_config(path: str | None = None) -> Config:
    """Load configuration from YAML file and environment variables.

    Config precedence: defaults < env vars < YAML file
    """
    config = Config()

    if path is None:
        # Search common locations
        candidates = [
            os.environ.get("MICRO_AGENT_CONFIG", ""),
            "./config.yaml",
            "./micro-agent.yaml",
            "~/.micro-agent/config.yaml",
            "/etc/micro-agent/config.yaml",
        ]
        for c in candidates:
            if c:
                p = Path(c).expanduser()
                if p.exists():
                    path = str(p)
                    break

    if path:
        p = Path(path).expanduser()
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
                config = Config(**data)
            log.info("Loaded config from %s", p)

    # Environment variable overrides
    if os.environ.get("MICRO_AGENT_PORT"):
        config.gateway.port = int(os.environ["MICRO_AGENT_PORT"])
    if os.environ.get("MICRO_AGENT_HOST"):
        config.gateway.host = os.environ["MICRO_AGENT_HOST"]
    if os.environ.get("MICRO_AGENT_MODEL"):
        config.pi.model = os.environ["MICRO_AGENT_MODEL"]
    if os.environ.get("MICRO_AGENT_PROVIDER"):
        config.pi.provider = os.environ["MICRO_AGENT_PROVIDER"]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config.telegram.bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        config.telegram.webhook_secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]

    return config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Start and stop the gateway with the FastAPI app."""
    global _gateway
    config = load_config()
    _gateway = Gateway(config)
    try:
        await _gateway.start()
        log.info("micro-agent gateway ready on %s:%d", config.gateway.host, config.gateway.port)
        yield
    finally:
        if _gateway:
            await _gateway.stop()


app = FastAPI(
    title="micro-agent",
    version="0.1.0",
    description="Pi + thin gateway + Karpathy-style markdown memory. Ultra-lightweight agent for self-hosted LLMs.",
    lifespan=lifespan,
)


# ── API Routes ───────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check endpoint."""
    if _gateway is None:
        return JSONResponse({"status": "starting"}, status_code=503)
    return {
        "status": "ok",
        "pi_running": _gateway.pi.is_running,
        "total_memories": len(_gateway.memory.get_all()),
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    """Send a message to the agent and get a response."""
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    try:
        response = await _gateway.process_message(request)
        return response.model_dump()
    except Exception as e:
        log.exception("Chat error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Send a message and stream the response."""
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")

    async def event_stream():
        async for token in _gateway.process_message_stream(request):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Telegram bot webhook endpoint."""
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")

    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    payload = await request.json()

    msg = payload.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not chat_id or not text:
        return {"ok": False, "error": "no message"}

    # Process through gateway
    chat_req = ChatRequest(
        message=text,
        conversation_id=f"tg:{chat_id}",
        user_id=str(chat_id),
    )
    response = await _gateway.process_message(chat_req)

    # Send back to Telegram
    from micro_agent.providers import TelegramProvider

    tg = TelegramProvider(
        bot_token=_gateway.config.telegram.bot_token,
        webhook_secret=_gateway.config.telegram.webhook_secret,
    )
    await tg.send_message(chat_id, response.message)

    return {"ok": True}


@app.post("/memory")
async def add_memory(title: str, content: str, mem_type: str = "semantic"):
    """Add an entry to persistent memory."""
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    from micro_agent.models import MemoryEntry, MemoryType

    entry = MemoryEntry(
        title=title,
        type=MemoryType(mem_type),
        content=content,
    )
    path = _gateway.memory.add(entry)
    return {"ok": True, "path": str(path)}


@app.get("/memory/search")
async def search_memory(q: str = ""):
    """Search persistent memory."""
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    results = _gateway.memory.search(q)
    return {"results": [e.model_dump() for e in results]}


@app.get("/memory")
async def list_memory():
    """List all memory entries."""
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    entries = _gateway.memory.get_all()
    return {
        "total": len(entries),
        "entries": [e.model_dump() for e in entries],
    }


@app.get("/stats")
async def stats():
    """Gateway statistics."""
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not ready")
    return _gateway.get_stats()


# ── CLI ──────────────────────────────────────────────────────────────


def main():
    """CLI entry point for micro-agent."""
    parser = argparse.ArgumentParser(description="micro-agent — ultra-lightweight agent gateway")
    parser.add_argument("--config", "-c", help="Path to config YAML")
    parser.add_argument("--port", "-p", type=int, default=0, help="Port to listen on")
    parser.add_argument("--host", default="", help="Host to bind to")
    parser.add_argument("--log-level", default="info", help="Logging level")
    parser.add_argument(
        "--set-webhook",
        metavar="URL",
        help="Register Telegram webhook and exit",
    )
    parser.add_argument(
        "--init-memory",
        action="store_true",
        help="Initialize memory directory and exit",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.config:
        os.environ["MICRO_AGENT_CONFIG"] = args.config

    config = load_config()

    if args.port:
        config.gateway.port = args.port
    if args.host:
        config.gateway.host = args.host
    if args.log_level:
        config.gateway.log_level = args.log_level

    if args.init_memory:
        from micro_agent.memory import MemoryStore

        store = MemoryStore(config.memory.path)
        log.info("Memory initialized at %s", store.base_path)
        return

    if args.set_webhook:
        from micro_agent.providers import TelegramProvider

        tg = TelegramProvider(
            bot_token=config.telegram.bot_token,
            webhook_secret=config.telegram.webhook_secret,
        )
        success = asyncio.run(tg.set_webhook(args.set_webhook))
        if success:
            log.info("Telegram webhook set to %s", args.set_webhook)
        else:
            log.error("Failed to set Telegram webhook")
        return

    # Run the server
    import uvicorn

    uvicorn.run(
        "micro_agent.main:app",
        host=config.gateway.host,
        port=config.gateway.port,
        log_level=config.gateway.log_level,
    )


if __name__ == "__main__":
    main()
