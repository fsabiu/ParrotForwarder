"""
Runtime adapters for the forwarder worker.

The worker process needs one small interface regardless of whether it is
driving the real Parrot/Olympe stack or a test/demo backend. This module keeps
that contract explicit so the worker loop stays simple and can be exercised on
hosts without Olympe installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..main import ParrotForwarder


@dataclass(frozen=True)
class RuntimeConfig:
    """Configuration passed from the supervisor to the worker runtime."""

    drone_ip: str = "192.168.53.1"
    telemetry_fps: int = 10
    video_fps: int = 30
    srt_port: int = 8890
    klv_port: int = 12345
    video_stats_interval: int = 30
    connect_retry_interval: float = 2.0


class ForwarderRuntime(Protocol):
    """Minimal surface the worker loop needs."""

    def connect(self) -> None:
        """Connect to the controller / drone. Raise on failure."""

    def start(self) -> None:
        """Start video + telemetry forwarding. Raise on failure."""

    def stop(self) -> None:
        """Stop forwarding."""

    def disconnect(self) -> None:
        """Disconnect the drone session."""

    def is_connected(self) -> bool:
        """Whether the controller/drone link is still alive."""

    def is_pipeline_running(self) -> bool:
        """Whether the video pipeline is still healthy enough to stream."""

    def telemetry_snapshot(self) -> dict[str, object]:
        """Return one dashboard-oriented telemetry sample."""

    def heartbeat_metrics(self, snapshot: dict[str, object]) -> dict[str, float]:
        """Extract the numeric metrics to attach to heartbeats."""


def _normalize_telemetry(snapshot: dict[str, object]) -> dict[str, object]:
    normalized = dict(snapshot)
    if "gps_fixed" in normalized and "gps_fix" not in normalized:
        normalized["gps_fix"] = normalized["gps_fixed"]
    return normalized


@dataclass
class V1ForwarderRuntime:
    """Adapter around the existing threaded forwarder implementation."""

    config: RuntimeConfig
    _forwarder: ParrotForwarder = field(init=False)

    def __post_init__(self) -> None:
        self._forwarder = ParrotForwarder(
            drone_ip=self.config.drone_ip,
            telemetry_fps=self.config.telemetry_fps,
            video_fps=self.config.video_fps,
            srt_port=self.config.srt_port,
            klv_port_start=self.config.klv_port,
            auto_reconnect=False,
            health_check_interval=int(self.config.connect_retry_interval),
            video_stats_interval=self.config.video_stats_interval,
            install_signal_handlers=False,
        )

    def connect(self) -> None:
        self._forwarder.connect(
            max_retries=1,
            retry_interval=self.config.connect_retry_interval,
        )

    def start(self) -> None:
        self._forwarder.start_forwarding()

    def stop(self) -> None:
        self._forwarder.stop_forwarding()

    def disconnect(self) -> None:
        self._forwarder.disconnect()

    def is_connected(self) -> bool:
        return self._forwarder.is_drone_connected()

    def is_pipeline_running(self) -> bool:
        video = self._forwarder.video_forwarder
        return bool(
            self._forwarder._is_forwarding
            and video is not None
            and video.gst_process is not None
            and video.gst_process.poll() is None
        )

    def telemetry_snapshot(self) -> dict[str, object]:
        telemetry = self._forwarder.telemetry_forwarder
        if telemetry is None:
            return {}
        return _normalize_telemetry(telemetry.get_telemetry_data())

    def heartbeat_metrics(self, snapshot: dict[str, object]) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for key in ("battery_percent", "rssi_dbm", "fps"):
            value = snapshot.get(key)
            if isinstance(value, bool):
                metrics[key] = float(value)
            elif isinstance(value, (int, float)):
                metrics[key] = float(value)
        return metrics


@dataclass
class MockForwarderRuntime:
    """Pure-Python stand-in used for tests and explicit demos."""

    config: RuntimeConfig
    connected: bool = field(init=False, default=False)
    streaming: bool = field(init=False, default=False)

    def connect(self) -> None:
        self.connected = True

    def start(self) -> None:
        if not self.connected:
            raise RuntimeError("mock runtime not connected")
        self.streaming = True

    def stop(self) -> None:
        self.streaming = False

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def is_pipeline_running(self) -> bool:
        return self.streaming

    def telemetry_snapshot(self) -> dict[str, object]:
        if not self.connected:
            return {}
        return {
            "battery_percent": 75,
            "gps_fix": True,
            "fps": float(self.config.video_fps),
        }

    def heartbeat_metrics(self, snapshot: dict[str, object]) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for key in ("battery_percent", "fps"):
            value = snapshot.get(key)
            if isinstance(value, (int, float)):
                metrics[key] = float(value)
        return metrics


def make_runtime(backend: str, config: RuntimeConfig) -> ForwarderRuntime:
    """Instantiate the requested runtime backend."""

    if backend == "real":
        return V1ForwarderRuntime(config=config)
    if backend == "mock":
        return MockForwarderRuntime(config=config)
    raise ValueError(f"unsupported worker backend: {backend}")
