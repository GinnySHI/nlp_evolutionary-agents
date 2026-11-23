"""HKGAI / DeepSeek chat-completions HTTP adapter; no vendor SDK dependency."""
from __future__ import annotations

import math
import random
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .config import Settings


class ProviderError(RuntimeError):
    """A safe diagnostic that never includes the upstream response body."""


class ProviderUnavailable(ProviderError):
    """Transient transport/service failure eligible for an explicitly configured backup."""


class OutputLimitError(ProviderError):
    """The output was incomplete; the engine may request a smaller action.

    Partial content is deliberately not exposed: it must never become an
    executable tool request. Repeating the same large request here would waste
    the budget without giving the agent a chance to split its work.
    """

    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        super().__init__(
            f"Model output reached the {max_tokens} token limit. No action was executed. "
            "Return a shorter single action; split large files into smaller writes."
        )


class _InvalidEnvelope(ValueError):
    """Internal, fixed diagnostic codes for malformed successful responses."""


class HKGAIClient:
    MAX_RETRY_DELAY = 30.0

    def _retry_delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        delay = 0.5 * 2**attempt
        if response is not None:
            header = response.headers.get("Retry-After", "").strip()
            try:
                if header.isascii() and header.isdecimal():
                    retry_after = float(header)
                else:
                    when = parsedate_to_datetime(header)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    retry_after = (when - datetime.now(timezone.utc)).total_seconds()
                if math.isfinite(retry_after) and retry_after >= 0:
                    delay = max(delay, retry_after)
            except (ValueError, TypeError, OverflowError):
                pass
        return min(self.MAX_RETRY_DELAY, delay + random.uniform(0, 0.5))

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        if not settings.api_key:
            key = "DEEPSEEK_API_KEY" if settings.provider == "deepseek" else "HKGAI_API_KEY"
            raise ProviderError(f"{key} is not configured; add it to your local .env file")
        self.settings = settings
        self.stats: dict[str, int] = defaultdict(int)
        self._json_format_supported = True
        self._reasoning_control_supported = bool(settings.reasoning_effort)
        self._fallback = None
        self.active_provider = settings.provider
        self._transport = transport
        base = settings.base_url.rstrip("/")
        self.endpoint = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        self.http = httpx.Client(
            timeout=httpx.Timeout(settings.request_timeout, connect=15),
            transport=transport, follow_redirects=False, trust_env=False,
            headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"},
        )

    @staticmethod
    def _unsupported_parameter(response: httpx.Response, names: tuple[str, ...]) -> bool:
        """Fallback only for an explicit unsupported-parameter error.

        Authentication, moderation and unrelated validation errors retain
        their normal failure path. The error body is inspected locally and is
        never included in logs or exceptions.
        """
        if response.status_code not in {400, 422}:
            return False
        try:
            error = response.json().get("error")
        except (ValueError, AttributeError):
            return False
        if not isinstance(error, dict):
            return False
        param = str(error.get("param", "")).lower()
        code = str(error.get("code", "")).lower()
        message = str(error.get("message", "")).lower()
        referenced = any(param == name or name in message for name in names)
        unsupported = code in {"unsupported_parameter", "unsupported_value", "unknown_parameter"} or any(
            phrase in message for phrase in ("not supported", "unsupported", "unknown parameter", "unrecognized parameter")
        )
        return referenced and unsupported

    @classmethod
    def _unsupported_json_format(cls, response: httpx.Response) -> bool:
        return cls._unsupported_parameter(response, ("response_format",))

    def _record_usage(self, data: Any) -> None:
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if type(value) is int and value >= 0:
                self.stats[key] += value
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            reasoning = details.get("reasoning_tokens")
            if type(reasoning) is int and reasoning >= 0:
                self.stats["reasoning_tokens"] += reasoning

    @staticmethod
    def _choice(data: Any) -> dict:
        if not isinstance(data, dict):
            raise _InvalidEnvelope("root_not_object")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise _InvalidEnvelope("missing_choice")
        return choices[0]

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        if self._fallback is None:
            try:
                return self._complete(messages, json_mode=json_mode)
            except ProviderUnavailable:
                if (not self.settings.fallback_enabled or not self.settings.deepseek_api_key
                        or self.settings.provider != "hkgai"
                        or "deepseek.com" in self.endpoint):
                    raise
                fallback = replace(self.settings, api_key=self.settings.deepseek_api_key,
                                   base_url="https://api.deepseek.com", model=self.settings.deepseek_model,
                                   provider="deepseek", fallback_enabled=False, deepseek_api_key="")
                # A paid-service switch keeps the same reasoning budget policy.
                self._fallback = HKGAIClient(fallback, transport=self._transport)
                self.active_provider = "deepseek"
                self.stats["provider_switches"] += 1
        before = dict(self._fallback.stats)
        try:
            return self._fallback.complete(messages, json_mode=json_mode)
        finally:
            for key, value in self._fallback.stats.items():
                self.stats[key] += value - before.get(key, 0)

    def _complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.model, "messages": messages,
            "temperature": 0.2, "max_tokens": self.settings.max_output_tokens,
            "stream": False,
        }
        if json_mode and self._json_format_supported:
            payload["response_format"] = {"type": "json_object"}
        # Both HKGAI-V3 and DeepSeek V4 are reasoning models whose thinking
        # tokens are billed inside max_tokens. Left at the service default,
        # a single large write can spend the entire budget on reasoning and
        # return finish_reason=length with no content at all. Capping the
        # effort keeps the visible answer affordable within one turn.
        if self._reasoning_control_supported:
            if self.settings.reasoning_effort == "none":
                payload["thinking"] = {"type": "disabled"}
            else:
                payload["reasoning_effort"] = self.settings.reasoning_effort
        # All retry causes share a three-request ceiling, including an optional
        # unsupported-format fallback. No output is executed by this adapter.
        for attempt in range(3):
            self.stats["requests"] += 1
            try:
                response = self.http.post(self.endpoint, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < 2:
                    time.sleep(self._retry_delay(attempt))
                    continue
                self.stats["errors"] += 1
                raise ProviderUnavailable(f"Model API network error: {type(exc).__name__}") from None
            if "response_format" in payload and self._unsupported_json_format(response) and attempt < 2:
                self._json_format_supported = False
                payload.pop("response_format")
                self.stats["json_mode_fallbacks"] += 1
                continue
            if (("reasoning_effort" in payload or "thinking" in payload)
                    and self._unsupported_parameter(response, ("reasoning_effort", "thinking")) and attempt < 2):
                self._reasoning_control_supported = False
                payload.pop("reasoning_effort", None)
                payload.pop("thinking", None)
                self.stats["reasoning_control_fallbacks"] += 1
                continue
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(self._retry_delay(attempt, response))
                continue
            if response.status_code >= 300:
                self.stats["errors"] += 1
                hints = {401: "invalid or expired API key", 402: "account balance or credit exhausted",
                         403: "model access denied", 404: "endpoint or model not found",
                         429: "rate or quota limit exceeded"}
                # 402 is not retried -- a balance does not refill on its own -- but it is
                # operator-fixable, so it pauses for a human instead of failing the task.
                # Treating it as fatal discards peer-accepted subtasks that cost real money.
                error_type = (ProviderUnavailable if response.status_code in {402, 429, 500, 502, 503, 504}
                              else ProviderError)
                raise error_type(f"Model API HTTP {response.status_code}: {hints.get(response.status_code, 'request failed')}; check configuration")
            try:
                try:
                    data = response.json()
                except ValueError:
                    raise _InvalidEnvelope("invalid_response_json") from None
                # Even a truncated or unusable completion may be billable.
                self._record_usage(data)
                choice = self._choice(data)
                if choice.get("finish_reason") == "length":
                    self.stats["truncated_responses"] += 1
                    self.stats["errors"] += 1
                    raise OutputLimitError(self.settings.max_output_tokens)
                if choice.get("finish_reason") == "content_filter":
                    self.stats["errors"] += 1
                    raise ProviderError("Model API declined this completion (content_filter).")
                message = choice.get("message")
                if not isinstance(message, dict):
                    raise _InvalidEnvelope("missing_message")
                if message.get("refusal"):
                    self.stats["errors"] += 1
                    raise ProviderError("Model API declined this completion (refusal).")
                content = message.get("content")
                if not isinstance(content, str):
                    raise _InvalidEnvelope("nontext_content")
                if not content.strip():
                    raise _InvalidEnvelope("empty_content")
                self.stats["calls"] += 1
                return content.strip()
            except _InvalidEnvelope as exc:
                self.stats["invalid_responses"] += 1
                if attempt < 2:
                    self.stats["protocol_retries"] += 1
                    time.sleep(self._retry_delay(attempt))
                    continue
                self.stats["errors"] += 1
                raise ProviderError(
                    f"Model response does not match the chat-completions protocol ({exc}); "
                    "stopped after 3 request attempts."
                ) from None
        raise ProviderError("Model request retries exhausted")

    def close(self) -> None:
        if self._fallback is not None:
            self._fallback.close()
        self.http.close()
