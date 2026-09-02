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
    # Keep the Fact verifier registered even when its optional credential is
    # absent so the public result distinguishes unavailable configuration from
    # an inconclusive search.
    registry.register("fact", FactVerifier(settings.tavily_api_key, max_results=settings.tavily_max_results))
    registry.register("code", CodeVerifier(settings.sandbox_image, timeout_seconds=settings.sandbox_timeout_seconds))
    return registry
