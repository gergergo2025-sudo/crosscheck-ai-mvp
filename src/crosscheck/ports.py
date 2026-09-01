"""Compatibility exports for provider-neutral extension boundaries."""

from .adapters import (
    AdapterError,
    AdapterHTTPError,
    AdapterProtocolError,
    AdapterTransportError,
    AdapterRegistry,
    AdapterUnavailable,
    BaseModelAdapter,
    DeepSeekAdapter,
    DeepSeekModelAdapter,
    DeterministicAdapter,
    DeterministicTestAdapter,
    ModelAdapter,
    OpenAIAdapter,
    OpenAICompatibleAdapter,
    OpenAIModelAdapter,
)
from .verifiers import DeterministicVerifier, StaticVerifier, Verifier, VerifierRegistry

__all__ = [
    "AdapterError",
    "AdapterHTTPError",
    "AdapterProtocolError",
    "AdapterTransportError",
    "AdapterRegistry",
    "AdapterUnavailable",
    "BaseModelAdapter",
    "DeepSeekAdapter",
    "DeepSeekModelAdapter",
    "DeterministicAdapter",
    "DeterministicTestAdapter",
    "ModelAdapter",
    "OpenAIAdapter",
    "OpenAICompatibleAdapter",
    "OpenAIModelAdapter",
    "DeterministicVerifier",
    "StaticVerifier",
    "Verifier",
    "VerifierRegistry",
]
