"""
Prometheus metrics for ParrotForwarder v2.

Every metric uses the ``parrot_forwarder_`` prefix and has a meaningful
help string so ``promtool check metrics`` is clean. The state machine
dispatcher in :mod:`parrot_forwarder.supervisor` is the single place
that calls :func:`record_state_transition` and :func:`record_restart` -
no metric increments scattered through business logic.

The set mirrors ``v2/architecture/state-machine.md#metrics-exported``
plus pipeline metrics (FPS, bitrate) from heartbeats.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

PREFIX = "parrot_forwarder_"


# ---------------------------------------------------------------------------
# Registry + metrics
# ---------------------------------------------------------------------------


class Metrics:
    """All metrics live in one registry, owned by this object.

    Using a dedicated registry (rather than the default global one) lets
    tests create isolated instances and avoids collisions when the whole
    test suite imports the module repeatedly.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()

        self.state = Gauge(
            f"{PREFIX}state",
            "Current supervisor state. 1 for the active state, 0 for others.",
            labelnames=("name",),
            registry=self.registry,
        )
        self.state_transitions_total = Counter(
            f"{PREFIX}state_transitions_total",
            "Number of state transitions.",
            labelnames=("from_state", "to_state", "reason"),
            registry=self.registry,
        )
        self.state_duration_seconds = Histogram(
            f"{PREFIX}state_duration_seconds",
            "Dwell time per state before a transition.",
            labelnames=("name",),
            registry=self.registry,
        )
        self.restarts_total = Counter(
            f"{PREFIX}restarts_total",
            "Number of forwarder restarts.",
            labelnames=("reason",),
            registry=self.registry,
        )
        self.heartbeat_lag_seconds = Gauge(
            f"{PREFIX}heartbeat_lag_seconds",
            "Seconds since the last worker heartbeat.",
            registry=self.registry,
        )

        # Pipeline metrics sourced from heartbeat ``metrics`` payloads.
        self.pipeline_fps = Gauge(
            f"{PREFIX}pipeline_fps",
            "Measured video pipeline frames per second when available.",
            registry=self.registry,
        )
        self.video_target_fps = Gauge(
            f"{PREFIX}video_target_fps",
            "Configured video target cadence in frames per second.",
            registry=self.registry,
        )
        self.pipeline_bitrate_kbps = Gauge(
            f"{PREFIX}pipeline_bitrate_kbps",
            "Current video pipeline bitrate in kbit/s.",
            registry=self.registry,
        )
        self.battery_percent = Gauge(
            f"{PREFIX}battery_percent",
            "Drone battery level.",
            registry=self.registry,
        )
        self.rssi_dbm = Gauge(
            f"{PREFIX}rssi_dbm",
            "Drone RF signal strength.",
            registry=self.registry,
        )
        self.telemetry_target_hz = Gauge(
            f"{PREFIX}telemetry_target_hz",
            "Configured telemetry/KLV target cadence in Hz.",
            registry=self.registry,
        )
        self.telemetry_actual_hz = Gauge(
            f"{PREFIX}telemetry_actual_hz",
            "Observed source-side telemetry/KLV cadence in Hz.",
            registry=self.registry,
        )
        self.klv_packets_sent = Gauge(
            f"{PREFIX}klv_packets_sent",
            "Number of KLV packets sent by the telemetry source.",
            registry=self.registry,
        )
        self.klv_send_errors = Gauge(
            f"{PREFIX}klv_send_errors",
            "Number of telemetry-to-KLV send errors observed by the source.",
            registry=self.registry,
        )
        self.telemetry_loop_max_ms = Gauge(
            f"{PREFIX}telemetry_loop_max_ms",
            "Maximum telemetry loop time in the recent source-side window.",
            registry=self.registry,
        )
        self.gstreamer_errors = Gauge(
            f"{PREFIX}gstreamer_errors",
            "Number of GStreamer errors observed by the source pipeline.",
            registry=self.registry,
        )
        self.gstreamer_warnings = Gauge(
            f"{PREFIX}gstreamer_warnings",
            "Number of GStreamer warnings observed by the source pipeline.",
            registry=self.registry,
        )
        self.srt_streaming = Gauge(
            f"{PREFIX}srt_streaming",
            "Whether the source SRT pipeline reports streaming: 1 yes, 0 no.",
            registry=self.registry,
        )

    # ------------------------------------------------------------------
    # Recorders
    # ------------------------------------------------------------------

    def record_state_transition(
        self, *, from_state: str, to_state: str, reason: str
    ) -> None:
        self.state_transitions_total.labels(
            from_state=from_state, to_state=to_state, reason=reason
        ).inc()
        self._set_current_state(to_state)

    def record_restart(self, *, reason: str) -> None:
        self.restarts_total.labels(reason=reason).inc()

    def record_heartbeat(
        self, *, lag_seconds: float, pipeline_metrics: dict[str, float]
    ) -> None:
        self.heartbeat_lag_seconds.set(lag_seconds)
        for source_key, gauge in (
            ("video_measured_fps", self.pipeline_fps),
            ("fps", self.pipeline_fps),
            ("video_target_fps", self.video_target_fps),
            ("bitrate_kbps", self.pipeline_bitrate_kbps),
            ("battery_percent", self.battery_percent),
            ("rssi_dbm", self.rssi_dbm),
            ("telemetry_target_hz", self.telemetry_target_hz),
            ("telemetry_actual_hz", self.telemetry_actual_hz),
            ("klv_packets_sent", self.klv_packets_sent),
            ("klv_send_errors", self.klv_send_errors),
            ("telemetry_loop_max_ms", self.telemetry_loop_max_ms),
            ("gstreamer_errors", self.gstreamer_errors),
            ("gstreamer_warnings", self.gstreamer_warnings),
            ("srt_streaming", self.srt_streaming),
        ):
            value = pipeline_metrics.get(source_key)
            if value is not None:
                gauge.set(float(value))

    def _set_current_state(self, current: str) -> None:
        """Set the current state gauge to 1 for ``current`` and 0 for others."""
        for name in _KNOWN_STATES:
            self.state.labels(name=name).set(1.0 if name == current else 0.0)


#: The full set of state names the state gauge publishes. Kept in sync
#: with :class:`parrot_forwarder.state_machine.State`.
_KNOWN_STATES = (
    "DISCONNECTED",
    "CONNECTING",
    "READY",
    "STREAMING",
    "DEGRADED",
    "RESTARTING",
)


# ---------------------------------------------------------------------------
# FastAPI integration
# ---------------------------------------------------------------------------


def register_metrics_route(app: FastAPI, metrics: Metrics, path: str = "/metrics") -> None:
    """Mount a ``/metrics`` endpoint on ``app`` backed by ``metrics.registry``."""
    from fastapi.responses import Response

    @app.get(path, include_in_schema=False)
    async def _metrics() -> Response:
        body = generate_latest(metrics.registry)
        return Response(content=body, media_type=CONTENT_TYPE_LATEST)
