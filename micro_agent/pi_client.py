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
from typing import AsyncIterator

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

        self._process: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._stderr_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

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

        # Start background stderr reader so Pi doesn't block on stderr buffer
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        # Wait briefly for process to be ready
        await asyncio.sleep(0.5)
        if self._process.returncode is not None:
            stderr_data = await self._read_stderr()
            raise PiConnectionError(
                f"Pi exited immediately (code {self._process.returncode}): {stderr_data}"
            )

        log.info("Pi RPC ready (pid=%d)", self._process.pid)

    async def _drain_stderr(self) -> None:
        """Continuously read and log stderr to prevent buffer deadlocks."""
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                log.debug("pi stderr: %s", line.decode(errors="replace").rstrip())
        except Exception:
            pass

    async def _read_stderr(self) -> str:
        """Read any buffered stderr output."""
        if self._process and self._process.stderr:
            try:
                leftover = await asyncio.wait_for(
                    self._process.stderr.read(), timeout=2.0
                )
                return leftover.decode("utf-8", errors="replace")
            except (asyncio.TimeoutError, OSError):
                pass
        return ""

    async def _next_id(self) -> str:
        self._req_id += 1
        return f"req-{self._req_id}"

    async def _send_line(self, data: dict) -> None:
        """Write a JSON line to Pi's stdin."""
        if not self._process or not self._process.stdin:
            raise PiConnectionError("Pi stdin is closed")
        line = json.dumps(data, ensure_ascii=False) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_line(self) -> dict | None:
        """Read a JSON line from Pi's stdout."""
        if not self._process or not self._process.stdout:
            raise PiConnectionError("Pi stdout reader not available")
        try:
            raw = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=self.timeout
            )
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
    ) -> dict:
        """Send a prompt to Pi and return the acknowledgement response."""
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

        resp = await self._read_line()
        if resp is None:
            raise PiConnectionError("Pi closed connection unexpectedly")

        return resp

    async def stream_events(self) -> AsyncIterator[dict]:
        """Stream events from Pi's RPC stdout.

        Yields raw event dicts until the agent finishes processing.
        """
        while True:
            line = await self._read_line()
            if line is None:
                break

            # Stop streaming when agent finishes
            if line.get("type") == "agent_end":
                yield line
                break

            yield line

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

    async def stop(self) -> None:
        """Gracefully stop the Pi subprocess."""
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

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
