"""Provider-neutral Model Adapter ports and model-provider integrations.

The first tracer used :class:`DeterministicAdapter` so that the application could
be exercised without credentials.  This module now also contains the two
OpenAI-compatible integrations required for the comparison slice.  Provider SDK
objects deliberately do not cross the adapter boundary: callers only receive an
``AdapterResult`` (raw text plus normalized call metadata).
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Mapping, Protocol

import httpx

from .contracts import AdapterResult


class AdapterError(RuntimeError):
    """Base error that is safe to convert into a provider status."""

    failure_class = "adapter_error"


class AdapterUnavailable(AdapterError):
    failure_class = "unavailable"


class AdapterTransportError(AdapterError):
    """A network/HTTP failure with no upstream body exposed to callers."""

    failure_class = "transport_error"


class AdapterProtocolError(AdapterError):
    """The upstream response did not match the chat-completions contract."""

    failure_class = "protocol_error"


class AdapterHTTPError(AdapterError):
    """A non-successful response from a model endpoint.

    ``status_code`` is useful to a later retry policy, while the exception text
    remains intentionally generic and never includes response bodies or headers.
    """

    failure_class = "http_error"

    def __init__(self, status_code: int) -> None:
        self.status_code = int(status_code)
        super().__init__(f"provider request failed with HTTP {self.status_code}")


class ModelAdapter(Protocol):
    provider: str

    async def generate(
        self,
        prompt: str,
        *,
        model: str,
        deadline: float | None = None,
        **options: Any,
    ) -> AdapterResult:
        """Return provider-neutral raw text and call metadata."""


class BaseModelAdapter(ABC):
    provider = "unknown"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        model: str,
        deadline: float | None = None,
        **options: Any,
    ) -> AdapterResult:
        raise NotImplementedError


def _content_text(content: Any) -> str:
    """Normalize the common OpenAI-compatible content shapes to plain text."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for item in content:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    pieces.append(text)
        return "".join(pieces)
    return ""


class OpenAICompatibleAdapter(BaseModelAdapter):
    """Adapter for the OpenAI chat-completions wire protocol.

    DeepSeek exposes the same protocol and is implemented as a small subclass
    below.  ``http_client`` is injectable so tests can use ``httpx.MockTransport``
    or an ASGI mock server without making real network calls.  A client supplied
    by a caller is never closed by the adapter.
    """

    provider = "openai-compatible"
    default_base_url = ""
    default_model = ""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        endpoint: str | None = None,
        model: str | None = None,
        public_model: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        http_client: httpx.AsyncClient | None = None,
        client: httpx.AsyncClient | None = None,
        max_response_chars: int = 120_000,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        # ``endpoint`` and ``client`` are accepted as readable aliases for
        # fixture authors; server configuration remains the only source of these
        # values in normal application usage.
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        selected_url = base_url or endpoint or self.default_base_url
        self.base_url = selected_url.rstrip("/")
        self.configured_model = (model or self.default_model).strip()
        self.public_model = (public_model or "").strip()
        self.timeout = timeout if timeout is not None else 10.0
        self.http_client = http_client or client
        # ``AdapterResult.raw_text`` is bounded at 120k characters as well; keep
        # the adapter bound no looser than the provider-neutral contract.
        self.max_response_chars = min(max(1, int(max_response_chars)), 120_000)
        self._headers = {str(key): str(value) for key, value in (headers or {}).items()}

    @property
    def requires_key(self) -> bool:
        return True

    def _effective_model(self, requested_model: str | None) -> str:
        requested = requested_model.strip() if isinstance(requested_model, str) else ""
        # The registry can expose a provider alias (``openai``) while the wire
        # request still needs a configured concrete model.  A direct caller's
        # concrete model always wins.
        aliases = {
            self.provider,
            self.__class__.__name__.removesuffix("Adapter").lower(),
            self.public_model,
        }
        if requested and requested not in aliases:
            return requested
        return self.configured_model

    def _request_url(self) -> str:
        # Both ``https://api.example/v1`` and a fully-qualified
        # ``.../chat/completions`` endpoint are convenient in tests/deployments.
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _request_headers(self) -> dict[str, str]:
        # API keys live only in this transport header.  They are never included in
        # the user prompt, AdapterResult, or a raised exception.
        headers = {"content-type": "application/json", **self._headers}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _post(self, payload: dict[str, Any], *, timeout: float | httpx.Timeout) -> httpx.Response:
        if not self.api_key and self.requires_key:
            raise AdapterUnavailable(f"{self.provider} API key is not configured")
        owned_client = self.http_client is None
        client = self.http_client or httpx.AsyncClient(timeout=timeout)
        try:
            try:
                response = await client.post(
                    self._request_url(),
                    headers=self._request_headers(),
                    json=payload,
                    timeout=timeout,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
                raise AdapterTransportError("provider request could not be completed") from exc
        finally:
            if owned_client:
                await client.aclose()
        return response

    def _parse_response(self, response: httpx.Response, *, model: str) -> tuple[str, dict[str, Any] | None, float | None]:
        if response.status_code < 200 or response.status_code >= 300:
            raise AdapterHTTPError(response.status_code)
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise AdapterProtocolError("provider returned malformed JSON") from exc
        if not isinstance(body, Mapping):
            raise AdapterProtocolError("provider response was not an object")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise AdapterProtocolError("provider response did not include choices")
        first_choice = choices[0]
        message = first_choice.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if content is None:
            # A few OpenAI-compatible implementations use ``text`` for a chat
            # choice.  Supporting it is harmless and keeps the boundary neutral.
            content = first_choice.get("text")
        raw_text = _content_text(content)
        if not raw_text:
            raise AdapterProtocolError("provider response did not include message content")
        usage = body.get("usage")
        token_usage: dict[str, Any] | None = None
        if isinstance(usage, Mapping):
            # Usage is diagnostic metadata, not an arbitrary provider payload.
            # Keep bounded scalar counters so secrets or nested response bodies
            # cannot be reflected by ModelAnswer serialization.
            normalized_usage: dict[str, Any] = {}
            for key, value in list(usage.items())[:32]:
                if not isinstance(key, str) or len(key) > 80:
                    continue
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    normalized_usage[key] = value
            token_usage = normalized_usage or None
        reported_cost: float | None = None
        for candidate in (body.get("cost"), body.get("usage", {}).get("cost") if isinstance(body.get("usage"), Mapping) else None):
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) and candidate >= 0:
                reported_cost = float(candidate)
                break
        del model  # identity is assigned by ``generate`` to the configured id.
        if self.api_key:
            # A misbehaving endpoint must not turn the configured credential into
            # persisted raw output or a repair prompt.
            raw_text = raw_text.replace(self.api_key, "[REDACTED]")
        return raw_text[: self.max_response_chars], token_usage, reported_cost

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        deadline: float | None = None,
        **options: Any,
    ) -> AdapterResult:
        if not isinstance(prompt, str):
            raise AdapterProtocolError("prompt must be text")
        started = time.perf_counter()
        effective_model = self._effective_model(model)
        timeout_value: float | httpx.Timeout = self.timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AdapterTransportError("provider request deadline elapsed")
            if isinstance(timeout_value, httpx.Timeout):
                def cap_timeout(value: float | None) -> float:
                    return remaining if value is None else min(value, remaining)

                timeout_value = httpx.Timeout(
                    cap_timeout(timeout_value.connect),
                    read=cap_timeout(timeout_value.read),
                    write=cap_timeout(timeout_value.write),
                    pool=cap_timeout(timeout_value.pool),
                )
            else:
                timeout_value = min(float(timeout_value), remaining)
        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": [{"role": "user", "content": prompt}],
            # Both required providers accept JSON mode.  It is a transport hint,
            # not part of the substantive Unified Prompt.
            "response_format": {"type": "json_object"},
        }
        # Permit only transport-safe options supplied by server code.  In
        # particular, never let a request field inject headers, credentials, or a
        # replacement prompt.  ``max_tokens``/temperature are intentionally
        # omitted unless explicitly passed by an adapter fixture or server config.
        for key in ("temperature", "max_tokens", "top_p", "seed"):
            if key in options and options[key] is not None:
                payload[key] = options[key]
        response = await self._post(payload, timeout=timeout_value)
        raw_text, token_usage, reported_cost = self._parse_response(response, model=effective_model)
        return AdapterResult(
            raw_text=raw_text,
            provider=self.provider,
            model=effective_model,
            latency_ms=(time.perf_counter() - started) * 1000,
            token_usage=token_usage,
            reported_cost=reported_cost,
            status="ok",
        )


class OpenAIAdapter(OpenAICompatibleAdapter):
    """OpenAI Chat Completions adapter."""

    provider = "openai"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """DeepSeek's OpenAI-compatible Chat Completions adapter."""

    provider = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"


# Readable compatibility aliases for callers that name adapters after their
# provider rather than the shorter ``*Adapter`` form.
OpenAIModelAdapter = OpenAIAdapter
DeepSeekModelAdapter = DeepSeekAdapter


class DeterministicAdapter:
    """A no-network Adapter used for local development and acceptance fixtures."""

    provider = "deterministic"

    def __init__(self, *, answer_prefix: str = "Deterministic answer") -> None:
        self.answer_prefix = answer_prefix
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        *,
        model: str = "deterministic",
        deadline: float | None = None,
        **options: Any,
    ) -> AdapterResult:
        del deadline, options
        started = time.perf_counter()
        self.prompts.append(prompt)
        question_match = re.search(r"^Question:\n(.*?)\n\nConstraints", prompt, re.DOTALL | re.MULTILINE)
        question = question_match.group(1).strip() if question_match else "the submitted question"
        type_match = re.search(r"^Selected question type:\s*(\w+)", prompt, re.MULTILINE)
        claim_type = type_match.group(1) if type_match else "fact"
        if claim_type not in {"fact", "code", "math", "logic", "opinion", "recommendation"}:
            claim_type = "fact"
        payload = {
            "answer": f"{self.answer_prefix}: {question}",
            "reasoning": "Generated by the deterministic acceptance adapter.",
            "claims": [
                {
                    "claim": f"The submitted question is: {question}",
                    "type": claim_type,
                    "confidence": 0.5,
                    "source": None,
                    "assumptions": None,
                }
            ],
            "constraints_check": {},
        }
        return AdapterResult(
            raw_text=json.dumps(payload, ensure_ascii=False),
            provider=self.provider,
            model=model,
            latency_ms=(time.perf_counter() - started) * 1000,
            status="ok",
        )


class UnavailableAdapter:
    """Placeholder for configured providers whose credentials are absent."""

    provider = "unavailable"

    def __init__(self, *, model: str, reason: str = "provider is not configured") -> None:
        self.model = model
        self.reason = reason

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        deadline: float | None = None,
        **options: Any,
    ) -> AdapterResult:
        del prompt, model, deadline, options
        raise AdapterUnavailable(self.reason)


class AdapterRegistry:
    """Stable model-name to Adapter mapping with no provider SDK leakage."""

    def __init__(self, adapters: Mapping[str, ModelAdapter] | None = None) -> None:
        self._adapters = dict(adapters or {})

    def register(self, model: str, adapter: ModelAdapter) -> None:
        self._adapters[model] = adapter

    def known_models(self) -> set[str]:
        return set(self._adapters)

    def usable_models(self) -> set[str]:
        return {
            name
            for name, adapter in self._adapters.items()
            if not isinstance(adapter, UnavailableAdapter)
        }

    def get(self, model: str) -> ModelAdapter:
        try:
            return self._adapters[model]
        except KeyError as exc:
            raise AdapterUnavailable(f"model '{model}' is not configured") from exc


def _production_model_config(model: str) -> tuple[str, str] | None:
    """Resolve a configured model identifier to ``(provider, wire model)``.

    Configuration commonly uses concrete names (``gpt-4o-mini`` and
    ``deepseek-chat``), while small deployments often prefer the stable aliases
    ``openai`` and ``deepseek``.  An explicit ``provider:model`` form supports
    custom model names without allowing a request to choose a URL or credential.
    """

    value = model.strip()
    lowered = value.casefold()
    if ":" in value:
        prefix, concrete = value.split(":", 1)
        concrete = concrete.strip()
        if prefix.casefold() in {"openai", "deepseek"} and concrete:
            return prefix.casefold(), concrete
    if lowered in {"openai", "openai-default", "gpt", "gpt-default"}:
        return "openai", OpenAIAdapter.default_model
    if lowered in {"deepseek", "deepseek-default"}:
        return "deepseek", DeepSeekAdapter.default_model
    if lowered.startswith(("gpt-", "o1-", "o3-", "o4-")):
        return "openai", value
    if lowered.startswith("deepseek-"):
        return "deepseek", value
    return None


def default_adapter_registry(models: list[str], settings: Any | None = None) -> AdapterRegistry:
    """Build the configured adapters without connecting to providers at startup."""

    registry = AdapterRegistry()
    for model in models:
        if model in {"deterministic", "test", "fake"}:
            registry.register(model, DeterministicAdapter())
            continue

        config = _production_model_config(model)
        if config is None:
            registry.register(model, UnavailableAdapter(model=model))
            continue
        provider, concrete_model = config
        if provider == "openai":
            api_key = getattr(settings, "openai_api_key", None)
            base_url = getattr(settings, "openai_base_url", None)
            adapter: ModelAdapter = OpenAIAdapter(
                api_key=api_key,
                base_url=base_url,
                model=concrete_model,
                public_model=model,
            ) if api_key else UnavailableAdapter(model=model, reason="openai provider is not configured")
        else:
            api_key = getattr(settings, "deepseek_api_key", None)
            base_url = getattr(settings, "deepseek_base_url", None)
            adapter = DeepSeekAdapter(
                api_key=api_key,
                base_url=base_url,
                model=concrete_model,
                public_model=model,
            ) if api_key else UnavailableAdapter(model=model, reason="deepseek provider is not configured")
        registry.register(model, adapter)
    return registry


# Explicit test-facing name keeps fixtures readable without introducing a second
# implementation or a provider-specific import path.
DeterministicTestAdapter = DeterministicAdapter
