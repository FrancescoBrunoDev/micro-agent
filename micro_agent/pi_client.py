"""Pi RPC subprocess manager.

Spins up `pi --mode rpc` as a subprocess and communicates via JSONL
over stdin/stdout. Implements the protocol documented at:
https://pi.dev/docs/latest/rpc
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator

from micro_agent.models import RPCCommand, RPCResponse

log = logging.getLogger(__name__)


class PiConnectionError(Exception):
    """Raised when Pi subprocess fails to start or becomes unresponsive."""


class PiRPCClient:
    """Manages a Pi agent subprocess in RPC mode.

    Usage:
        client = PiRPCClient(binary="pi", provider="openai", model="...")
        await client.start()
        response = await client.prompt("Hello!")
        async for event in client.stream_events():
            ...
        await client.stop()
    """

    def __init__(
        self,
        binary: str = "pi",
        provider: str | None = None,
        model: str | None = None,
        session_dir: str | None = None,
        extra_args: list[str] | None = None,
        timeout: float = 120.0,
    ):
        self.binary = binary
        self.provider = provider
        self.model = model
        self.session_dir = session_dir
        self.extra_args = extra_args or []
        self.timeout = timeout

        self._process: subprocess.Popen | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._req_id = 0
        self._pending: dict[str, asyncio.Future] = {}

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    async def start(self) -> None:
        """Start Pi in RPC mode and wait for readiness."""
        if self.is_running:
            return

        cmd = [self.binary, "--mode", "rpc"]
        if self.provider:
            cmd.extend(["--provider", self.provider])
        if self.model:
            cmd.extend(["--model", self.model])
        if self.session_dir:
            cmd.extend(["--session-dir", self.session_dir])
        cmd.extend(["--no-session"])
        cmd.extend(self.extra_args)

        log.info("Starting Pi RPC: %s", " ".join(cmd))

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PAGER": "cat", "EDITOR": "cat"},
            )
        except FileNotFoundError as e:
            raise PiConnectionError(
                f"Pi binary '{self.binary}' not found. Install with: "
                f"npm install -g @earendil-works/pi-coding-agent"
            ) from e

        # Wrap stdio in asyncio streams
        loop = asyncio.get_event_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        if self._process.stdout:
            await loop.connect_read_pipe(lambda: protocol, self._process.stdout)

        self._writer = asyncio.StreamWriter(
            asyncio.get_event_loop()._proactor or asyncio.get_event_loop()._selector,
            asyncio.StreamWriterProtocol(
                lambda: asyncio.Transport(None)
            ),
            self._process.stdin,
            None,
        ) if hasattr(asyncio, 'StreamWriterProtocol') else None  # fallback

        # Simplified writer setup
        self._writer_raw = self._process.stdin

        # Wait briefly for process to be ready
        await asyncio.sleep(0.5)
        if self._process.returncode is not None:
            stderr = await self._read_stderr()
            raise PiConnectionError(
                f"Pi exited immediately (code {self._process.returncode}): {stderr}"
            )

        log.info("Pi RPC ready (pid=%d)", self._process.pid)

    async def _read_stderr(self) -> str:
        """Read any available stderr output."""
        if self._process and self._process.stderr:
            try:
                data = await asyncio.wait_for(
                    self._process.stderr.read(), timeout=2.0
                )
                return data.decode("utf-8", errors="replace")
            except (asyncio.TimeoutError, OSError):
                pass
        return ""

    async def _next_id(self) -> str:
        self._req_id += 1
        return f"req-{self._req_id}"

    async def _send_line(self, data: dict) -> None:
        """Write a JSON line to Pi's stdin."""
        if not self._writer_raw or self._writer_raw.is_closed():
            raise PiConnectionError("Pi stdin is closed")
        line = json.dumps(data, ensure_ascii=False) + "\n"
        self._writer_raw.write(line.encode("utf-8"))
        await asyncio.get_event_loop().run_in_executor(None, self._writer_raw.flush)

    async def _read_line(self) -> dict | None:
        """Read a JSON line from Pi's stdout."""
        if not self._reader:
            raise PiConnectionError("Pi stdout reader not available")
        try:
            raw = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise PiConnectionError(f"Pi RPC timed out after {self.timeout}s")
        if not raw:
            return None  # EOF
        line = raw.decode("utf-8").strip()
        if not line:
            return None
        return json.loads(line)

    async def prompt(
        self,
        message: str,
        images: list[dict] | None = None,
    ) -> RPCResponse:
        """Send a prompt to Pi and wait for the acknowledgement response.

        The actual assistant response comes via events (stream_events).
        """
        req_id = await self._next_id()
        cmd = {
            "id": req_id,
            "type": "prompt",
            "message": message,
            "streamingBehavior": "steer",
        }
        if images:
            cmd["images"] = images

        await self._send_line(cmd)

        # Read the response (success/fail acknowledgement)
        resp = await self._read_line()
        if resp is None:
            raise PiConnectionError("Pi closed connection unexpectedly")

        return RPCResponse(**resp)

    async def stream_events(self) -> AsyncIterator[dict]:
        """Stream events from Pi's RPC stdout.

        Yields raw event dicts until the agent finishes processing.
        """
        while True:
            line = await self._read_line()
            if line is None:
                break

            # Responses have 'type': 'response' and an 'id'
            # Events have a 'type' but no 'id'
            if line.get("type") == "response":
                # Correlate with pending futures
                req_id = line.get("id", "")
                if req_id in self._pending:
                    self._pending[req_id].set_result(line)
                    del self._pending[req_id]
                continue

            # It's an event
            yield line

            # Stop streaming when agent finishes
            if line.get("type") == "agent_end":
                break

    async def bash(self, command: str) -> dict:
        """Execute a shell command via Pi and return the result."""
        req_id = await self._next_id()
        cmd = {"id": req_id, "type": "bash", "command": command}
        await self._send_line(cmd)

        resp = await self._read_line()
        if resp is None:
            raise PiConnectionError("Pi closed connection unexpectedly")
        return resp

    async def get_state(self) -> dict:
        """Get Pi's current session state."""
        req_id = await self._next_id()
        await self._send_line({"id": req_id, "type": "get_state"})
        resp = await self._read_line()
        return resp if resp else {}

    async def compact(self, instructions: str = "") -> dict:
        """Manually compact Pi's conversation context."""
        cmd: dict = {"type": "compact"}
        if instructions:
            cmd["customInstructions"] = instructions
        await self._send_line(cmd)
        resp = await self._read_line()
        return resp if resp else {}

    async def abort(self) -> None:
        """Abort the current Pi operation."""
        await self._send_line({"type": "abort"})
        # No response expected for abort

    async def stop(self) -> None:
        """Gracefully stop the Pi subprocess."""
        if self._process and self._process.returncode is None:
            log.info("Stopping Pi RPC (pid=%d)", self._process.pid)
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning("Pi did not terminate gracefully, killing")
                self._process.kill()
                await self._process.wait()
        self._process = None
        self._reader = None
        self._writer_raw = None
