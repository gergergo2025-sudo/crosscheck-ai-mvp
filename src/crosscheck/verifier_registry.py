"""Default Verifier registration.

Each Verifier module registers itself here so the query pipeline stays free of
provider-specific wiring.  A Verifier whose dependency or configuration is
missing is simply not registered; the registry then falls back to the
deterministic verifier, which reports uncertainty instead of a pass.
"""

from __future__ import annotations

from .config import Settings
from .verifiers import CodeVerifier, FactVerifier, VerifierRegistry


def default_verifier_registry(settings: Settings) -> VerifierRegistry:
    """Build the configured Verifier registry without contacting any service."""

    registry = VerifierRegistry()
    if settings.tavily_api_key:
        registry.register("fact", FactVerifier(settings.tavily_api_key, max_results=settings.tavily_max_results))
    registry.register("code", CodeVerifier(settings.sandbox_image, timeout_seconds=settings.sandbox_timeout_seconds))
    return registry
