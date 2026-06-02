"""Telegram webhook handler for micro-agent."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class TelegramProvider:
    """Handles Telegram bot webhook integration.

    Usage:
        tg = TelegramProvider(token="...", secret="...")
        # Verify webhook:
        data = await tg.verify_webhook(payload, x_telegram_bot_api_secret_token)
        # Send reply:
        await tg.send_message(chat_id, text)
    """

    def __init__(self, bot_token: str = "", webhook_secret: str = ""):
        self.bot_token = bot_token
        self.webhook_secret = webhook_secret
        self._api_base = f"https://api.telegram.org/bot{bot_token}" if bot_token else ""

    async def verify_webhook(
        self, payload: dict[str, Any], secret_token: str | None = None
    ) -> dict | None:
        """Verify and parse a Telegram webhook payload.

        Returns the message dict if valid, None otherwise.
        """
        # Validate secret token if configured
        if self.webhook_secret and secret_token:
            if not hmac.compare_digest(self.webhook_secret, secret_token):
                log.warning("Telegram webhook secret token mismatch")
                return None

        # Extract message
        message = payload.get("message", {}) or payload.get("edited_message", {})
        if not message:
            return None

        return message

    async def send_message(
        self, chat_id: int, text: str, reply_to: int | None = None
    ) -> bool:
        """Send a message to a Telegram chat."""
        if not self._api_base:
            log.warning("Telegram not configured, cannot send message")
            return False

        data: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_to:
            data["reply_to_message_id"] = reply_to

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self._api_base}/sendMessage", json=data
                )
                result = resp.json()
                if not result.get("ok"):
                    log.error("Telegram send failed: %s", result.get("description"))
                    return False
                return True
        except httpx.RequestError as e:
            log.error("Telegram send error: %s", e)
            return False

    async def set_webhook(self, url: str) -> bool:
        """Register the webhook URL with Telegram."""
        if not self._api_base:
            return False

        data = {"url": url}
        if self.webhook_secret:
            data["secret_token"] = self.webhook_secret

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self._api_base}/setWebhook", json=data
                )
                result = resp.json()
                return result.get("ok", False)
        except httpx.RequestError as e:
            log.error("Telegram setWebhook error: %s", e)
            return False

    async def delete_webhook(self) -> bool:
        """Remove the webhook registration."""
        if not self._api_base:
            return False

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{self._api_base}/deleteWebhook")
                result = resp.json()
                return result.get("ok", False)
        except httpx.RequestError as e:
            log.error("Telegram deleteWebhook error: %s", e)
            return False
