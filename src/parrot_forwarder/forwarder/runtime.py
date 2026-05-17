"""
Runtime adapters for the forwarder worker.

The worker process needs one small interface regardless of whether it is
driving the real Parrot/Olympe stack or a test/demo backend. This module keeps
that contract explicit so the worker loop stays simple and can be exercised on
hosts without Olympe installed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..main import ParrotForwarder


@dataclass(frozen=True)
class RuntimeConfig:
    """Configuration passed from the supervisor to the worker runtime."""

    drone_ip: str = "192.168.53.1"
    video_ip: str | None = None
    device_kind: Literal["drone", "skycontroller"] = "drone"
    telemetry_fps: int = 30
    include_raw_sdk_state_in_klv: bool = False
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


def _compact(data: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in data.items()
        if value is not None and value != {} and value != []
    }


def _axis_bounds(minimum: object, maximum: object) -> dict[str, object] | None:
    bounds = _compact({"min": minimum, "max": maximum})
    return bounds or None


def _make_olympe_factory(
    device_kind: Literal["drone", "skycontroller"],
) -> Callable[[str], object]:
    def _factory(ip: str) -> object:
        import olympe

        if device_kind == "skycontroller":
            return olympe.SkyController(ip)
        return olympe.Drone(ip)

    return _factory


def _normalize_telemetry(snapshot: dict[str, object]) -> dict[str, object]:
    raw = dict(snapshot)
    gps_fix = raw.get("gps_fix", raw.get("gps_fixed"))

    normalized: dict[str, object] = {
        "timestamp": raw.get("timestamp"),
        "sequence": raw.get("sequence"),
        "source_id": raw.get("source_id"),
        "source_name": raw.get("source_name"),
        "battery_percent": raw.get("battery_percent"),
        "gps_fix": gps_fix,
        "position_valid": raw.get("position_valid"),
        "rssi_dbm": raw.get("rssi_dbm"),
        "telemetry_hz": raw.get("telemetry_hz", raw.get("telemetry_target_hz")),
        "telemetry_target_hz": raw.get("telemetry_target_hz", raw.get("telemetry_hz")),
        "telemetry_actual_hz": raw.get("telemetry_actual_hz"),
        "video_target_fps": raw.get("video_target_fps", raw.get("video_fps", raw.get("fps"))),
        "video_measured_fps": raw.get("video_measured_fps"),
        # Legacy key retained only when the source explicitly provides video FPS.
        # Do not fall back to telemetry_hz: that made telemetry cadence look like
        # measured video cadence in downstream dashboards.
        "fps": raw.get("fps"),
    }

    position = _compact(
        {
            "valid": raw.get("position_valid"),
            "source": raw.get("position_source"),
            "message": raw.get("position_message"),
            "is_default": raw.get("position_is_default"),
            "gps_fix": gps_fix,
            "satellites": raw.get("position_satellites"),
            "latitude": raw.get("position_latitude"),
            "longitude": raw.get("position_longitude"),
            "altitude_msl_m": raw.get("position_altitude_msl"),
            "altitude_agl_m": raw.get("altitude_agl"),
            "altitude_relative_takeoff_m": raw.get("altitude_relative_takeoff_m"),
            "ground_altitude_msl_m": raw.get("ground_altitude_msl"),
        }
    )
    position_accuracy = _compact(
        {
            "latitude": raw.get("position_latitude_accuracy_m"),
            "longitude": raw.get("position_longitude_accuracy_m"),
            "altitude": raw.get("position_altitude_accuracy_m"),
        }
    )
    if position_accuracy:
        position["accuracy_m"] = position_accuracy
    position_home = _compact(
        {
            "latitude": raw.get("home_latitude"),
            "longitude": raw.get("home_longitude"),
            "altitude_msl_m": raw.get("home_altitude_msl"),
        }
    )
    if position_home:
        position["home"] = position_home
    klv_position = _compact(
        {
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "altitude_msl_m": raw.get("altitude"),
        }
    )
    if klv_position:
        position["klv"] = klv_position
    raw_position = _compact(
        {
            "gps_location": _compact(
                {
                    "latitude": raw.get("gps_location_latitude_raw"),
                    "longitude": raw.get("gps_location_longitude_raw"),
                    "altitude_msl_m": raw.get("gps_location_altitude_msl_raw"),
                }
            ),
            "position_changed": _compact(
                {
                    "latitude": raw.get("position_changed_latitude_raw"),
                    "longitude": raw.get("position_changed_longitude_raw"),
                    "altitude_msl_m": raw.get("position_changed_altitude_msl_raw"),
                }
            ),
        }
    )
    if raw_position:
        position["raw"] = raw_position
    if position:
        normalized["position"] = position

    attitude = _compact(
        {
            "roll_rad": raw.get("roll"),
            "pitch_rad": raw.get("pitch"),
            "yaw_rad": raw.get("yaw"),
            "roll_deg": raw.get("roll_deg"),
            "pitch_deg": raw.get("pitch_deg"),
            "yaw_deg": raw.get("yaw_deg"),
            "heading_deg": raw.get("heading_deg"),
        }
    )
    if attitude:
        normalized["attitude"] = attitude

    speed = _compact(
        {
            "x_mps": raw.get("speed_x"),
            "y_mps": raw.get("speed_y"),
            "z_mps": raw.get("speed_z"),
            "horizontal_mps": raw.get("speed_horizontal_mps"),
            "total_mps": raw.get("speed_total_mps"),
            "airspeed_mps": raw.get("airspeed_mps"),
        }
    )
    if speed:
        normalized["speed"] = speed

    signal = _compact(
        {
            "rssi_dbm": raw.get("rssi_dbm"),
            "link_quality_level": raw.get("link_quality_level"),
            "link_quality_bits": raw.get("link_quality_bits"),
            "probable_4g_interference": raw.get("link_quality_4g_interference"),
            "external_perturbation": raw.get("link_quality_external_perturbation"),
        }
    )
    if signal:
        normalized["signal"] = signal

    gimbal = _compact(
        {
            "id": raw.get("gimbal_id"),
            "yaw_frame_of_reference": raw.get("gimbal_yaw_frame_of_reference"),
            "pitch_frame_of_reference": raw.get("gimbal_pitch_frame_of_reference"),
            "roll_frame_of_reference": raw.get("gimbal_roll_frame_of_reference"),
            "offset_update_state": raw.get("gimbal_offset_update_state"),
        }
    )
    gimbal_absolute = _compact(
        {
            "yaw": raw.get("gimbal_yaw_abs"),
            "pitch": raw.get("gimbal_pitch_abs"),
            "roll": raw.get("gimbal_roll_abs"),
        }
    )
    if gimbal_absolute:
        gimbal["absolute_deg"] = gimbal_absolute
    gimbal_relative = _compact(
        {
            "yaw": raw.get("gimbal_yaw_rel"),
            "pitch": raw.get("gimbal_pitch_rel"),
            "roll": raw.get("gimbal_roll_rel"),
        }
    )
    if gimbal_relative:
        gimbal["relative_deg"] = gimbal_relative
    gimbal_offsets = _compact(
        {
            "yaw": raw.get("gimbal_offset_yaw"),
            "pitch": raw.get("gimbal_offset_pitch"),
            "roll": raw.get("gimbal_offset_roll"),
        }
    )
    if gimbal_offsets:
        gimbal["offset_deg"] = gimbal_offsets
    gimbal_bounds = _compact(
        {
            "yaw": _axis_bounds(raw.get("gimbal_offset_min_yaw"), raw.get("gimbal_offset_max_yaw")),
            "pitch": _axis_bounds(
                raw.get("gimbal_offset_min_pitch"),
                raw.get("gimbal_offset_max_pitch"),
            ),
            "roll": _axis_bounds(raw.get("gimbal_offset_min_roll"), raw.get("gimbal_offset_max_roll")),
        }
    )
    if gimbal_bounds:
        gimbal["offset_bounds_deg"] = gimbal_bounds
    if gimbal:
        normalized["gimbal"] = gimbal

    camera = _compact(
        {
            "id": raw.get("camera_id"),
            "sensor_width_mm": raw.get("camera_sensor_width_mm", raw.get("camera_sensor_width")),
            "sensor_height_mm": raw.get("camera_sensor_height_mm", raw.get("camera_sensor_height")),
            "focal_length_mm": raw.get("camera_focal_length_mm", raw.get("camera_focal_length")),
            "base_focal_length_mm": raw.get(
                "camera_focal_length_base_mm",
                raw.get("camera_focal_length_base"),
            ),
            "zoom_level": raw.get("camera_zoom_level"),
            "h_fov_deg": raw.get("camera_h_fov_deg", raw.get("sensor_h_fov")),
            "v_fov_deg": raw.get("camera_v_fov_deg", raw.get("sensor_v_fov")),
        }
    )
    camera_alignment = _compact(
        {
            "yaw": raw.get("cam_align_yaw"),
            "pitch": raw.get("cam_align_pitch"),
            "roll": raw.get("cam_align_roll"),
        }
    )
    if camera_alignment:
        camera["alignment_deg"] = camera_alignment
    camera_alignment_bounds = _compact(
        {
            "yaw": _axis_bounds(raw.get("cam_align_min_yaw"), raw.get("cam_align_max_yaw")),
            "pitch": _axis_bounds(raw.get("cam_align_min_pitch"), raw.get("cam_align_max_pitch")),
            "roll": _axis_bounds(raw.get("cam_align_min_roll"), raw.get("cam_align_max_roll")),
        }
    )
    if camera_alignment_bounds:
        camera["alignment_bounds_deg"] = camera_alignment_bounds
    camera_recording = _compact(
        {
            "available": raw.get("camera_recording_available"),
            "state": raw.get("camera_recording_state"),
            "start_timestamp_ms": raw.get("camera_recording_start_timestamp_ms"),
            "start_time": raw.get("camera_recording_start_time"),
        }
    )
    if camera_recording:
        camera["recording"] = camera_recording
    if camera:
        normalized["camera"] = camera

    flight = _compact(
        {
            "state": raw.get("flying_state"),
            "alert_state": raw.get("alert_state"),
            "wind_state": raw.get("wind_state"),
            "vibration_level": raw.get("vibration_level"),
            "heading_locked_state": raw.get("heading_locked_state"),
        }
    )
    navigate_home = _compact(
        {
            "state": raw.get("return_home_state"),
            "reason": raw.get("return_home_reason"),
            "min_altitude_m": raw.get("return_home_min_altitude_m"),
            "min_bound_m": raw.get("return_home_min_altitude_min_m"),
            "max_bound_m": raw.get("return_home_min_altitude_max_m"),
        }
    )
    if navigate_home:
        flight["return_home"] = navigate_home
    hovering_warning = _compact(
        {
            "no_gps_too_dark": raw.get("hovering_warning_no_gps_too_dark"),
            "no_gps_too_high": raw.get("hovering_warning_no_gps_too_high"),
        }
    )
    if hovering_warning:
        flight["hovering_warning"] = hovering_warning
    if flight:
        normalized["flight"] = flight

    storage = _compact(
        {
            "free_space_mb": raw.get("storage_free_space_mb"),
            "recording_time_remaining_min": raw.get("storage_recording_time_remaining_min"),
            "photo_remaining": raw.get("storage_photo_remaining"),
        }
    )
    if storage:
        normalized["storage"] = storage

    system = _compact(
        {
            "product_name": raw.get("product_name"),
            "software_version": raw.get("product_software_version"),
            "hardware_version": raw.get("product_hardware_version"),
        }
    )
    motor_flights = _compact(
        {
            "total_flights": raw.get("motor_total_flights"),
            "last_flight_duration_s": raw.get("motor_last_flight_duration_s"),
            "total_flight_duration_s": raw.get("motor_total_flight_duration_s"),
        }
    )
    if motor_flights:
        system["motor_flights"] = motor_flights
    if system:
        normalized["system"] = system

    normalized["raw"] = raw
    return _compact(normalized)


@dataclass
class V1ForwarderRuntime:
    """Adapter around the existing threaded forwarder implementation."""

    config: RuntimeConfig
    _forwarder: ParrotForwarder = field(init=False)

    def __post_init__(self) -> None:
        self._forwarder = ParrotForwarder(
            drone_ip=self.config.drone_ip,
            video_ip=self.config.video_ip,
            telemetry_fps=self.config.telemetry_fps,
            video_fps=self.config.video_fps,
            srt_port=self.config.srt_port,
            klv_port_start=self.config.klv_port,
            auto_reconnect=False,
            health_check_interval=int(self.config.connect_retry_interval),
            video_stats_interval=self.config.video_stats_interval,
            include_raw_sdk_state_in_klv=self.config.include_raw_sdk_state_in_klv,
            drone_factory=_make_olympe_factory(self.config.device_kind),
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
        if not self._forwarder._is_forwarding or video is None:
            return False
        if hasattr(video, "is_streaming"):
            return bool(video.is_streaming())
        return bool(video.gst_process is not None and video.gst_process.poll() is None)

    def telemetry_snapshot(self) -> dict[str, object]:
        telemetry = self._forwarder.telemetry_forwarder
        if telemetry is None:
            return {}
        normalized = _normalize_telemetry(telemetry.get_telemetry_data())
        normalized["telemetry_target_hz"] = float(self.config.telemetry_fps)
        normalized["video_target_fps"] = float(self.config.video_fps)
        return normalized

    def heartbeat_metrics(self, snapshot: dict[str, object]) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for key in ("battery_percent", "rssi_dbm", "video_target_fps", "video_measured_fps"):
            value = snapshot.get(key)
            if isinstance(value, bool):
                metrics[key] = float(value)
            elif isinstance(value, (int, float)):
                metrics[key] = float(value)
        telemetry = self._forwarder.telemetry_forwarder
        if telemetry is not None and hasattr(telemetry, "metrics_snapshot"):
            telemetry_metrics = telemetry.metrics_snapshot()
            if isinstance(telemetry_metrics, dict):
                for key, value in telemetry_metrics.items():
                    if isinstance(value, (int, float)):
                        metrics[key] = float(value)
        video = self._forwarder.video_forwarder
        if video is not None:
            metrics["srt_streaming"] = 1.0 if self.is_pipeline_running() else 0.0
            for attr, key in (
                ("gst_errors", "gstreamer_errors"),
                ("gst_warnings", "gstreamer_warnings"),
            ):
                value = getattr(video, attr, None)
                if isinstance(value, (int, float)):
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
            "source_id": "mock_anafi",
            "source_name": "Mock Anafi",
            "battery_percent": 75,
            "gps_fix": True,
            "telemetry_hz": float(self.config.telemetry_fps),
            "fps": float(self.config.video_fps),
        }

    def heartbeat_metrics(self, snapshot: dict[str, object]) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for key in ("battery_percent", "fps"):
            value = snapshot.get(key)
            if isinstance(value, (int, float)):
                metrics[key] = float(value)
        metrics["telemetry_target_hz"] = float(self.config.telemetry_fps)
        metrics["telemetry_actual_hz"] = float(self.config.telemetry_fps)
        metrics["srt_streaming"] = 1.0 if self.streaming else 0.0
        return metrics


def make_runtime(backend: str, config: RuntimeConfig) -> ForwarderRuntime:
    """Instantiate the requested runtime backend."""

    if backend == "real":
        return V1ForwarderRuntime(config=config)
    if backend == "mock":
        return MockForwarderRuntime(config=config)
    raise ValueError(f"unsupported worker backend: {backend}")
