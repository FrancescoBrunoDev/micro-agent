"""Pydantic models for micro-agent."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Configuration ───────────────────────────────────────────────────


class ProviderConfig(BaseModel):
    """LLM provider configuration for Pi."""

    name: str
    model: str = ""
    base_url: str | None = None
    api_key_env: str = ""


class TelegramConfig(BaseModel):
    bot_token: str = ""
    webhook_secret: str = ""
    allowed_chat_ids: list[int] = Field(default_factory=list)


class MemoryConfig(BaseModel):
    path: str = "~/.micro-agent/memory"
    max_context_files: int = 3
    auto_compact_threshold: int = 500  # files before compaction


class PiConfig(BaseModel):
    binary: str = "pi"
    provider: str = "openai"
    model: str = ""
    session_dir: str = "~/.micro-agent/sessions"
    extra_args: list[str] = Field(default_factory=list)


class GatewayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "info"


class Config(BaseModel):
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    pi: PiConfig = Field(default_factory=PiConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)


# ── RPC Protocol ─────────────────────────────────────────────────────


class RPCCommand(BaseModel):
    """A command sent to Pi's RPC stdin."""

    id: str = ""
    type: str  # "prompt", "steer", "follow_up", "bash", "abort", etc.
    message: str = ""
    streamingBehavior: str = "steer"


class RPCResponse(BaseModel):
    """A response from Pi's RPC stdout."""

    id: str = ""
    type: str = "response"
    command: str = ""
    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class RPCEvent(BaseModel):
    """An event streamed from Pi's RPC stdout."""

    type: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ── Memory Models ────────────────────────────────────────────────────


class MemoryType(str, Enum):
    episodic = "episodic"  # conversation facts, specific events
    semantic = "semantic"  # general knowledge, user preferences
    procedural = "procedural"  # how-to, workflows


class MemoryEntry(BaseModel):
    """A single memory entry stored as a markdown file."""

    title: str
    type: MemoryType = MemoryType.episodic
    created: str = ""
    updated: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str = ""  # what triggered this memory
    content: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"


# ── Gateway Models ───────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Incoming chat message."""

    message: str
    conversation_id: str = ""
    user_id: str = ""
    images: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Response from the agent."""

    message: str
    conversation_id: str
    memories_written: int = 0
    tokens_used: int = 0
