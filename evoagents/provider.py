"""HKGAI / DeepSeek chat-completions HTTP adapter; no vendor SDK dependency."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

import httpx

from .config import Settings


class ProviderError(RuntimeError):
    pass


class HKGAIClient:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        if not settings.api_key:
            raise ProviderError("HKGAI_API_KEY is not configured; add it to your local .env file")
        self.settings = settings
        self.stats: dict[str, int] = defaultdict(int)
        base = settings.base_url.rstrip("/")
        self.endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        self.http = httpx.Client(
            timeout=httpx.Timeout(settings.request_timeout, connect=15),
            transport=transport, follow_redirects=False, trust_env=False,
            headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"},
        )

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        # Text JSON protocol works even when a vendor does not support response_format/tool_calls.
        payload: dict[str, Any] = {
            "model": self.settings.model, "messages": messages,
            "temperature": 0.2, "max_tokens": self.settings.max_output_tokens,
            "stream": False,
        }
        for attempt in range(3):
            self.stats["requests"] += 1
            try:
                response = self.http.post(self.endpoint, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < 2:
                    time.sleep(0.5 * 2**attempt)
                    continue
                self.stats["errors"] += 1
                raise ProviderError(f"Model API network error: {type(exc).__name__}") from None
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(0.5 * 2**attempt)
                continue
            if response.status_code >= 300:
                self.stats["errors"] += 1
                hints = {401: "invalid or expired API key", 403: "model access denied", 404: "endpoint or model not found", 429: "rate or quota limit exceeded"}
                # Do not print server bodies: an upstream error can echo request credentials.
                raise ProviderError(f"Model API HTTP {response.status_code}: {hints.get(response.status_code, 'request failed')}; check configuration")
            try:
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty content")
                if choice.get("finish_reason") == "length":
                    raise ProviderError("Model output reached the token limit; increase EVO_MAX_OUTPUT_TOKENS or narrow the task")
                usage = data.get("usage")
                if not isinstance(usage, dict):
                    usage = {}
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if isinstance(usage.get(key), int):
                        self.stats[key] += usage[key]
                self.stats["calls"] += 1
                return content.strip()
            except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
                self.stats["errors"] += 1
                raise ProviderError("Model response does not match the chat-completions protocol") from None
        raise ProviderError("Model request retries exhausted")

    def close(self) -> None:
        self.http.close()
