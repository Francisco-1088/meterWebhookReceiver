import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_TIMEOUT = 10.0


async def send_to_teams(webhook_url: str, payload: dict[str, Any]) -> bool:
    """POST an Adaptive Card payload to a Teams Incoming Webhook with retry/backoff."""
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

            if response.status_code in (200, 202):
                logger.info("Card delivered to Teams (HTTP %d)", response.status_code)
                return True

            # Teams returns 429 as a body string, not always as HTTP 429
            body = response.text
            if response.status_code == 429 or "429" in body:
                wait = 2**attempt
                logger.warning("Teams rate limit hit, retrying in %ds", wait)
                await asyncio.sleep(wait)
                continue

            logger.error(
                "Teams webhook returned %d: %s", response.status_code, body
            )
            return False

        except httpx.RequestError as exc:
            if attempt < _MAX_RETRIES - 1:
                wait = 2**attempt
                logger.warning("Network error sending to Teams, retry in %ds: %s", wait, exc)
                await asyncio.sleep(wait)
            else:
                logger.error("Giving up after %d attempts: %s", _MAX_RETRIES, exc)

    return False
