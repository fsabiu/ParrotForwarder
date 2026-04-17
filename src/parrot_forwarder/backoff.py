"""
Exponential backoff with jitter for supervisor restart scheduling.

Pure functions and a tiny stateful helper. Seedable RNG so tests are
deterministic. Mirrors the policy in
``v2/architecture/state-machine.md#backoff-policy``:

    delay = min(max_delay, base_delay * 2^(consecutive_failures - 1)) + jitter

    base_delay = 1 s, max_delay = 60 s, jitter in [0, 1)
    consecutive_failures resets to 0 after 60 s of continuous STREAMING.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BackoffPolicy:
    """Immutable backoff parameters.

    All durations are seconds. Validated at construction; raises
    :class:`ValueError` on out-of-range inputs so we never silently produce
    a negative or infinite delay.
    """

    base_seconds: float = 1.0
    max_seconds: float = 60.0
    jitter_seconds: float = 1.0
    #: After this many seconds of continuous STREAMING, the failure counter
    #: resets to zero. Matches the spec's "healthy window".
    healthy_reset_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.base_seconds <= 0:
            raise ValueError("base_seconds must be > 0")
        if self.max_seconds <= 0:
            raise ValueError("max_seconds must be > 0")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds must be >= base_seconds")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be >= 0")
        if self.healthy_reset_seconds <= 0:
            raise ValueError("healthy_reset_seconds must be > 0")


def compute_delay(
    consecutive_failures: int,
    policy: BackoffPolicy,
    rng: random.Random | None = None,
) -> float:
    """Compute the next restart delay in seconds.

    Args:
        consecutive_failures: Number of consecutive failed attempts. Must be
            ``>= 0``. ``0`` means "no failures yet"; callers typically increment
            before calling here, so the first real call passes ``1``.
        policy: Backoff parameters to apply.
        rng: Optional :class:`random.Random` used for jitter. When ``None``,
            the module-level default random is used. Tests must pass a seeded
            instance for determinism.

    Returns:
        A non-negative float: the number of seconds to sleep before the next
        restart attempt. Clamped to ``[0, max_seconds + jitter_seconds]``.
    """
    if consecutive_failures < 0:
        raise ValueError("consecutive_failures must be >= 0")
    if consecutive_failures == 0:
        return 0.0

    # 2^(k-1) grows quickly; clamp the exponent to avoid overflow for
    # absurdly large failure counts.
    exponent = min(consecutive_failures - 1, 30)
    raw = policy.base_seconds * (2**exponent)
    capped = min(raw, policy.max_seconds)

    if policy.jitter_seconds > 0:
        jitter_sample: float = rng.random() if rng is not None else random.random()
        jitter = jitter_sample * policy.jitter_seconds
    else:
        jitter = 0.0

    return float(capped + jitter)


@dataclass
class BackoffState:
    """Tiny stateful helper tracking consecutive failures.

    The supervisor keeps one of these per forwarder subprocess. After a
    streaming window (``>= healthy_reset_seconds``) the counter resets so a
    drone that's flaky-then-stable doesn't accumulate backoff forever.
    """

    policy: BackoffPolicy = field(default_factory=BackoffPolicy)
    consecutive_failures: int = 0
    rng: random.Random | None = None

    def record_failure(self) -> float:
        """Increment the counter and return the delay for the next attempt."""
        self.consecutive_failures += 1
        return compute_delay(self.consecutive_failures, self.policy, self.rng)

    def record_streaming_window(self, seconds: float) -> None:
        """Reset the counter if the window is long enough.

        Args:
            seconds: How long the forwarder has been STREAMING cleanly.
        """
        if seconds >= self.policy.healthy_reset_seconds:
            self.consecutive_failures = 0

    def reset(self) -> None:
        """Forcefully clear the counter (e.g. after operator reset)."""
        self.consecutive_failures = 0
