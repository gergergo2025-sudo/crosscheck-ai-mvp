"""Small process-local controls for the anonymous public API.

The limits intentionally sit at the HTTP boundary: rejected requests never enter
the query coordinator and therefore cannot open provider calls or create durable
Reports.  A distributed deployment should additionally enforce an edge/gateway
limit, but the in-process guard remains useful for local and single-worker runs.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Iterable


def _normalise_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _proxy_matches(peer: str | None, configured: Iterable[str]) -> bool:
    peer_ip = _normalise_ip(peer)
    if peer_ip is None:
        return False
    address = ipaddress.ip_address(peer_ip)
    for token in configured:
        try:
            if "/" in token:
                if address in ipaddress.ip_network(token, strict=False):
                    return True
            elif address == ipaddress.ip_address(token):
                return True
        except ValueError:
            continue
    return False


def client_identity(
    *,
    peer: str | None,
    forwarded_for: str | None,
    real_ip: str | None = None,
    trusted_proxies: Iterable[str] = (),
) -> str:
    """Resolve a rate-limit identity with fail-closed proxy semantics.

    Forwarded headers are considered only when the immediate ASGI peer is a
    configured proxy.  Otherwise a caller cannot spoof another client's bucket by
    sending ``X-Forwarded-For``.  The first valid address is used because it is the
    original client in the conventional proxy chain.
    """

    if _proxy_matches(peer, trusted_proxies):
        candidates: list[str] = []
        if forwarded_for:
            candidates.extend(part.strip() for part in forwarded_for.split(","))
        if real_ip:
            candidates.append(real_ip.strip())
        for candidate in candidates:
            normalized = _normalise_ip(candidate)
            if normalized:
                return normalized
    return _normalise_ip(peer) or "unknown"


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    """Bounded fixed/sliding-window limiter with injectable clock for tests."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("rate limit and window must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> RateDecision:
        now = self.clock()
        async with self._lock:
            events = self._events[key]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - now + 0.999))
                return RateDecision(False, retry_after)
            events.append(now)
            # Prevent unbounded memory growth from many one-shot identities while
            # retaining active buckets.  This is a soft sweep, not part of the
            # correctness path.
            if len(self._events) > 10_000:
                stale = [name for name, values in self._events.items() if not values or values[-1] <= cutoff]
                for name in stale[:2_000]:
                    self._events.pop(name, None)
            return RateDecision(True)


class NonBlockingConcurrency:
    """Semaphore-like gate which rejects instead of queueing work."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("concurrency limit must be positive")
        self._semaphore = asyncio.Semaphore(limit)

    async def try_acquire(self) -> bool:
        # ``Semaphore.acquire_nowait`` is not available on all supported Python
        # versions.  Inspecting the private counter is safe within this process and
        # avoids creating an unbounded waiter queue.
        value = getattr(self._semaphore, "_value", 0)
        if value <= 0:
            return False
        self._semaphore._value = value - 1  # type: ignore[attr-defined]
        return True

    def release(self) -> None:
        self._semaphore.release()


# Friendly compatibility names for deployments/tests that refer to the boundary
# abstractions generically rather than by their implementation detail.
RateLimiter = SlidingWindowRateLimiter
ConcurrencyLimiter = NonBlockingConcurrency
resolve_client_ip = client_identity
