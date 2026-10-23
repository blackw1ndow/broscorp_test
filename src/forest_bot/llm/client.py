"""Thin wrapper over Groq: JSON answers, retries and the free-tier rate limit."""

import json
import logging
import re
from typing import Any

import groq

log = logging.getLogger(__name__)


class LLMBusyError(Exception):
    """Groq keeps answering 429 or is unavailable: the animal should try again in a minute."""


class LLMBadResponseError(Exception):
    """The model did not return a JSON object."""


class LLMClient:
    def __init__(self, api_key: str, *, max_retries: int = 3, timeout: float = 60.0) -> None:
        # The SDK retries 429 and 5xx itself and honours the retry-after header
        self._client = groq.AsyncGroq(api_key=api_key, max_retries=max_retries, timeout=timeout)

    async def complete_json(
        self, model: str, system: str, user: str, *, max_tokens: int = 1500
    ) -> dict[str, Any]:
        for attempt in (1, 2):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    # Reasoning tokens count against the 8K tokens-per-minute limit
                    reasoning_effort="low",
                    max_completion_tokens=max_tokens,
                    temperature=0.2,
                )
            except (groq.RateLimitError, groq.APIConnectionError, groq.InternalServerError) as e:
                raise LLMBusyError(str(e)) from e
            except groq.BadRequestError as e:
                # JSON mode rejects a reply that is not valid JSON; one more try usually works
                if attempt == 2:
                    raise LLMBadResponseError(str(e)) from e
                log.warning("Groq rejected the reply (%s), retrying", e)
                continue

            content = response.choices[0].message.content or ""
            try:
                return parse_json_object(content)
            except LLMBadResponseError:
                if attempt == 2:
                    raise
                log.warning("Not a JSON object from %s: %r, retrying", model, content[:200])
        raise AssertionError("unreachable")


def parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    # Some replies wrap the object in ```json fences
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMBadResponseError(content[:200]) from e
    if not isinstance(value, dict):
        raise LLMBadResponseError(content[:200])
    return value
