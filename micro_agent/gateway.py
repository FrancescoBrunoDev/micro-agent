"""Core gateway orchestration.

The gateway sits between the user (Telegram/HTTP) and Pi RPC.
It manages:
- Message routing to Pi
- Memory retrieval & writing (Karpathy-style markdown)
- Context injection per turn
- Conversation state
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from micro_agent.memory import MemoryStore
from micro_agent.models import (
    Config,
    ChatRequest,
    ChatResponse,
    MemoryEntry,
    MemoryType,
    PiConfig,
)
from micro_agent.pi_client import PiRPCClient

log = logging.getLogger(__name__)

# System prompt template — deliberately minimal to keep token overhead low
DEFAULT_SYSTEM_PROMPT = """You are micro-agent, an ultra-lightweight AI assistant running on a self-hosted LLM.

## Core Principles
- Be concise. Prefer short responses.
- Write code and run it when uncertain — LLMs are good at this.
- Use the available tools: read, bash, edit, write.
- If asked to extend yourself, do so by writing code, not downloading plugins.

## Memory
- You have access to persistent markdown memory.
- Explicitly note when you learn something worth remembering.
- To save: just say "MEMORY: <fact to remember>"
- To recall: mention the topic and relevant context will be injected.
"""

# Pattern the LLM can use to signal memory writes
MEMORY_SIGNAL = "MEMORY:"


def _extract_memory_updates(text: str) -> list[str]:
    """Extract memory write signals from agent response."""
    updates = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(MEMORY_SIGNAL):
            content = line[len(MEMORY_SIGNAL) :].strip()
            if content:
                updates.append(content)
    return updates


class Gateway:
    """Core orchestration gateway.

    Usage:
        config = Config(...)
        gateway = Gateway(config)
        await gateway.start()
        response = await gateway.process_message(ChatRequest(message="Hello"))
        await gateway.stop()
    """

    def __init__(self, config: Config):
        self.config = config
        self.memory = MemoryStore(config.memory.path)
        self.pi = PiRPCClient(
            binary=config.pi.binary,
            provider=config.pi.provider,
            model=config.pi.model or None,
            session_dir=config.pi.session_dir,
            extra_args=config.pi.extra_args,
        )
        self._system_prompt = DEFAULT_SYSTEM_PROMPT
        self._conversations: dict[str, list[dict]] = {}

    async def start(self) -> None:
        """Start the gateway and connect to Pi."""
        log.info(
            "Starting gateway (mem=%s, pi=%s, model=%s)",
            self.config.memory.path,
            self.config.pi.binary,
            self.config.pi.model or "default",
        )
        await self.pi.start()

    async def stop(self) -> None:
        """Gracefully shut down the gateway."""
        await self.pi.stop()

    async def process_message(self, request: ChatRequest) -> ChatResponse:
        """Process a single message through the full gateway pipeline.

        1. Retrieve relevant memory context
        2. Build system prompt with context
        3. Send to Pi
        4. Stream events and collect response
        5. Save any memory updates from the response
        """
        conv_id = request.conversation_id or "default"

        # 1. Retrieve relevant memory
        memory_context = self.memory.get_relevant_context(
            request.message,
            max_files=self.config.memory.max_context_files,
        )

        # 2. Build the full prompt with memory context
        full_prompt = self._build_prompt(request.message, memory_context)

        # 3. Send to Pi
        await self.pi.prompt(full_prompt)

        # 4. Stream events and collect the final response
        final_text = ""
        async for event in self.pi.stream_events():
            if event.get("type") == "message_update":
                data = event.get("data", {})
                delta = data.get("delta", "")
                if delta:
                    final_text += delta
            elif event.get("type") == "message_end":
                data = event.get("data", {})
                if data.get("text"):
                    final_text = data["text"]

        # 5. Extract and save memory updates
        memories_written = 0
        if final_text:
            updates = _extract_memory_updates(final_text)
            for update in updates:
                self.memory.add(
                    MemoryEntry(
                        title=update[:60],
                        type=MemoryType.semantic,
                        tags=["auto"],
                        source=f"conversation:{conv_id}",
                        content=update,
                    )
                )
                memories_written += 1

        return ChatResponse(
            message=final_text,
            conversation_id=conv_id,
            memories_written=memories_written,
        )

    async def process_message_stream(
        self, request: ChatRequest
    ) -> AsyncIterator[str]:
        """Process a message and stream the response token by token."""
        conv_id = request.conversation_id or "default"

        memory_context = self.memory.get_relevant_context(
            request.message,
            max_files=self.config.memory.max_context_files,
        )
        full_prompt = self._build_prompt(request.message, memory_context)

        await self.pi.prompt(full_prompt)

        final_text = ""
        async for event in self.pi.stream_events():
            if event.get("type") == "message_update":
                data = event.get("data", {})
                delta = data.get("delta", "")
                if delta:
                    final_text += delta
                    yield delta
            elif event.get("type") == "message_end":
                data = event.get("data", {})
                if data.get("text"):
                    final_text = data["text"]
                    # Yield any remaining text not covered by deltas
                    if delta and not data.get("text", "").startswith(
                        final_text[: len(delta)]
                    ):
                        yield data["text"]

        # Save memory updates
        if final_text:
            updates = _extract_memory_updates(final_text)
            for update in updates:
                self.memory.add(
                    MemoryEntry(
                        title=update[:60],
                        type=MemoryType.semantic,
                        tags=["auto"],
                        source=f"conversation:{conv_id}",
                        content=update,
                    )
                )

    def _build_prompt(self, message: str, memory_context: str) -> str:
        """Build the full prompt to send to Pi.

        Keeps the prompt minimal — only the message + any relevant memory.
        """
        parts = [self._system_prompt]

        if memory_context:
            parts.append(memory_context)

        parts.append(f"\n## User Message\n{message}")

        return "\n\n".join(parts)

    async def save_memory(self, content: str, mem_type: MemoryType = MemoryType.semantic) -> None:
        """Save an explicit memory entry."""
        self.memory.add(
            MemoryEntry(
                title=content[:60],
                type=mem_type,
                tags=["manual"],
                source="user",
                content=content,
            )
        )

    async def search_memory(self, query: str) -> list[MemoryEntry]:
        """Search persistent memory."""
        return self.memory.search(query)

    def get_stats(self) -> dict:
        """Get gateway statistics."""
        all_mem = self.memory.get_all()
        return {
            "total_memories": len(all_mem),
            "by_type": {
                t.value: len(
                    self.memory.get_all(mem_type=t)
                )
                for t in MemoryType
            },
            "pi_running": self.pi.is_running,
        }
