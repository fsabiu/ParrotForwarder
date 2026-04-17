"""
Tests for :mod:`parrot_forwarder.backoff`.

Deterministic - every test that exercises jitter uses a seeded RNG.
"""

from __future__ import annotations

import random

import pytest

from parrot_forwarder.backoff import BackoffPolicy, BackoffState, compute_delay

# ---------------------------------------------------------------------------
# BackoffPolicy validation
# ---------------------------------------------------------------------------


def test_default_policy_matches_spec() -> None:
    p = BackoffPolicy()
    assert p.base_seconds == 1.0
    assert p.max_seconds == 60.0
    assert p.jitter_seconds == 1.0
    assert p.healthy_reset_seconds == 60.0


def test_policy_rejects_non_positive_base() -> None:
    with pytest.raises(ValueError):
        BackoffPolicy(base_seconds=0)


def test_policy_rejects_max_below_base() -> None:
    with pytest.raises(ValueError):
        BackoffPolicy(base_seconds=10, max_seconds=1)


def test_policy_rejects_negative_jitter() -> None:
    with pytest.raises(ValueError):
        BackoffPolicy(jitter_seconds=-0.1)


# ---------------------------------------------------------------------------
# compute_delay
# ---------------------------------------------------------------------------


def test_compute_delay_zero_failures_is_zero() -> None:
    assert compute_delay(0, BackoffPolicy()) == 0.0


def test_compute_delay_rejects_negative_failures() -> None:
    with pytest.raises(ValueError):
        compute_delay(-1, BackoffPolicy())


def test_compute_delay_without_jitter_is_exact() -> None:
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=60.0, jitter_seconds=0.0)
    # 1 * 2^0 = 1
    assert compute_delay(1, policy) == 1.0
    # 1 * 2^1 = 2
    assert compute_delay(2, policy) == 2.0
    # 1 * 2^2 = 4
    assert compute_delay(3, policy) == 4.0
    # 1 * 2^5 = 32
    assert compute_delay(6, policy) == 32.0


def test_compute_delay_caps_at_max() -> None:
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=60.0, jitter_seconds=0.0)
    # 2^10 = 1024 - must be clamped to 60.
    assert compute_delay(11, policy) == 60.0
    # And staying there as failures grow further.
    assert compute_delay(20, policy) == 60.0


def test_compute_delay_handles_massive_failure_counts_without_overflow() -> None:
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=60.0, jitter_seconds=0.0)
    # Would overflow naively (2^9999 is absurd); the implementation clamps the
    # exponent so we just get max_seconds.
    assert compute_delay(9999, policy) == 60.0


def test_compute_delay_adds_bounded_jitter() -> None:
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=60.0, jitter_seconds=1.0)
    rng = random.Random(42)
    delay = compute_delay(1, policy, rng=rng)
    # Base=1 + jitter in [0,1) -> delay in [1, 2)
    assert 1.0 <= delay < 2.0


def test_compute_delay_is_deterministic_with_seeded_rng() -> None:
    policy = BackoffPolicy()
    a = compute_delay(3, policy, rng=random.Random(7))
    b = compute_delay(3, policy, rng=random.Random(7))
    assert a == b


# ---------------------------------------------------------------------------
# BackoffState helper
# ---------------------------------------------------------------------------


def test_state_record_failure_increments_and_returns_growing_delay() -> None:
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=60.0, jitter_seconds=0.0)
    state = BackoffState(policy=policy, rng=random.Random(0))
    assert state.consecutive_failures == 0
    assert state.record_failure() == 1.0  # 1st: 2^0
    assert state.record_failure() == 2.0  # 2nd: 2^1
    assert state.record_failure() == 4.0  # 3rd: 2^2
    assert state.consecutive_failures == 3


def test_state_record_streaming_window_resets_when_long_enough() -> None:
    policy = BackoffPolicy(
        base_seconds=1.0, max_seconds=60.0, jitter_seconds=0.0, healthy_reset_seconds=60.0
    )
    state = BackoffState(policy=policy)
    state.consecutive_failures = 5
    # A short healthy window must not reset.
    state.record_streaming_window(10.0)
    assert state.consecutive_failures == 5
    # A window >= healthy_reset_seconds resets.
    state.record_streaming_window(60.0)
    assert state.consecutive_failures == 0


def test_state_reset_forces_counter_to_zero() -> None:
    state = BackoffState()
    state.consecutive_failures = 7
    state.reset()
    assert state.consecutive_failures == 0


def test_state_five_consecutive_failures_delays_match_spec() -> None:
    """Spec check: 5 consecutive failures with base=1, max=60, no jitter."""
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=60.0, jitter_seconds=0.0)
    state = BackoffState(policy=policy)
    delays = [state.record_failure() for _ in range(5)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]
