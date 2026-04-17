"""
TelemetryForwarder - Handles telemetry data reading and forwarding.

Reads drone telemetry at specified FPS and forwards via KLV (MISB 0601) over
UDP. The worker/dashboard path consumes the same snapshot dictionary, so this
module now carries both:

1. Legacy flat fields used by the v1 KLV encoder.
2. Richer raw/derived fields for the v2 dashboard and downstream geolocation
   consumers.
"""

from __future__ import annotations

import logging
import math
import socket
import threading
import time
from datetime import UTC, datetime
from typing import Any

from olympe.messages.ardrone3.GPSSettingsState import (
    GPSFixStateChanged,
    HomeChanged,
    ReturnHomeMinAltitudeChanged,
)
from olympe.messages.ardrone3.GPSState import NumberOfSatelliteChanged
from olympe.messages.ardrone3.PilotingState import (
    AirSpeedChanged,
    AlertStateChanged,
    AltitudeAboveGroundChanged,
    AltitudeChanged,
    AttitudeChanged,
    FlyingStateChanged,
    GpsLocationChanged,
    HeadingLockedStateChanged,
    HoveringWarning,
    NavigateHomeStateChanged,
    PositionChanged,
    SpeedChanged,
    VibrationLevelChanged,
    WindStateChanged,
)
from olympe.messages.ardrone3.SettingsState import MotorFlightsStatusChanged
from olympe.messages.camera import (
    alignment_offsets,
    recording_state,
    zoom_level,
)
from olympe.messages.common.CommonState import (
    BatteryStateChanged,
    LinkSignalQuality,
    MassStorageInfoRemainingListChanged,
    WifiSignalChanged,
)
from olympe.messages.common.SettingsState import (
    ProductNameChanged,
    ProductVersionChanged,
)
from olympe.messages.gimbal import attitude as GimbalAttitude, offsets as GimbalOffsets

from .klv_encoder import encode_telemetry_to_klv


DEFAULT_LATITUDE = 36.71549027372183
DEFAULT_LONGITUDE = -4.287949979844388
DEFAULT_ALTITUDE_MSL_M = 10.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _enum_text(value: object) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value_f = float(value)
        if math.isfinite(value_f):
            return value_f
    return None


def _valid_lat_lon(latitude: float | None, longitude: float | None) -> bool:
    if latitude is None or longitude is None:
        return False
    if latitude == 500.0 or longitude == 500.0:
        return False
    return -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0


def _normalize_heading_deg(yaw_rad: float | None) -> float | None:
    if yaw_rad is None:
        return None
    return math.degrees(yaw_rad) % 360.0


def _klv_safe_altitude_msl(altitude_msl: float | None) -> float | None:
    if altitude_msl is None:
        return None
    return altitude_msl if 0.0 <= altitude_msl < 6553.5 else None


def _camera_fov_degrees(
    sensor_width_mm: float,
    sensor_height_mm: float,
    focal_length_mm: float,
) -> tuple[float, float]:
    """Return horizontal/vertical FOV in degrees.

    ``FOCAL_LENGTH_EQ_MM`` is stored as 35 mm equivalent. The downstream
    geolocation code already compensates for that by swapping to a virtual
    36 mm full-frame width when the focal length looks equivalent rather than
    physical. Reuse the same assumption here so the published FOV agrees with
    the downstream pipeline.
    """

    if sensor_width_mm <= 0 or sensor_height_mm <= 0 or focal_length_mm <= 0:
        raise ValueError("sensor dimensions and focal length must be positive")

    effective_sensor_width_mm = (
        36.0 if focal_length_mm > 15.0 and sensor_width_mm < 10.0 else sensor_width_mm
    )
    effective_sensor_height_mm = effective_sensor_width_mm * (
        sensor_height_mm / sensor_width_mm
    )
    h_fov = math.degrees(
        2.0 * math.atan(effective_sensor_width_mm / (2.0 * focal_length_mm))
    )
    v_fov = math.degrees(
        2.0 * math.atan(effective_sensor_height_mm / (2.0 * focal_length_mm))
    )
    return h_fov, v_fov



class TelemetryForwarder(threading.Thread):
    """
    Handles reading and forwarding telemetry data from the drone.
    Runs in a separate thread and collects telemetry at specified intervals.
    Forwards telemetry as KLV (MISB 0601) over UDP to localhost for FFmpeg to consume.
    """
    
    def __init__(self, drone, fps=10, klv_port=12345, name="TelemetryForwarder"):
        """
        Initialize the telemetry forwarder.
        
        Args:
            drone: Olympe Drone instance
            fps: Frames per second for telemetry updates
            klv_port: Local UDP port for KLV data (for FFmpeg to consume)
            name: Thread name
        """
        super().__init__(name=name, daemon=True)
        self.drone = drone
        self.fps = fps
        self.interval = 1.0 / fps
        self.running = False
        self.telemetry_count = 0
        self.logger = logging.getLogger(f"{__name__}.{name}")
        
        # --- NEW: SENSOR PARAMETERS (initialization only) ---
        # Sensor format: 1/2.4" CMOS (~6.3 x 4.7 mm)
        self.SENSOR_WIDTH_MM = 6.3
        self.SENSOR_HEIGHT_MM = 4.7
        self.FOCAL_LENGTH_EQ_MM = 23.0  # 35mm equivalent at 1x zoom
        
        # KLV forwarding configuration - always send to localhost for FFmpeg
        self.local_klv_host = '127.0.0.1'
        self.local_klv_port = klv_port
        self.udp_socket = None
        
        # Initialize UDP socket for KLV forwarding (raw KLV for GStreamer)
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setblocking(True)
            self.logger.info(f"✓ KLV UDP socket initialized - sending to {self.local_klv_host}:{self.local_klv_port}")
        except Exception as e:
            self.logger.error(f"✗ Failed to create KLV UDP socket: {e}")
            self.udp_socket = None
        
        # Performance tracking
        self.start_time = None
        self.last_stats_time = None
        self.stats_interval = 5.0  # Report stats every 5 seconds
        self.loop_times = []
        self.max_loop_times = 100  # Keep last 100 loop times for stats
        self.packets_sent = 0
        self.send_errors = 0

    def _safe_get_state(self, message: Any) -> dict[str, Any] | None:
        try:
            state = self.drone.get_state(message)
        except Exception as exc:
            error_msg = str(exc)
            if "state is uninitialized" in error_msg:
                return None
            self.logger.debug(
                "get_state(%s) failed: %s",
                getattr(message, "__name__", str(message)),
                exc,
            )
            return None
        return state if isinstance(state, dict) else None

    def get_telemetry_data(self):
        """
        Collect current telemetry data from the drone.

        Returns:
            dict: Dictionary containing all telemetry data
        """
        telemetry = {
            "timestamp": _utc_now_iso(),
            "sequence": self.telemetry_count,
        }

        battery = self._safe_get_state(BatteryStateChanged)
        if battery:
            telemetry["battery_percent"] = battery.get("percent")

        # Camera intrinsics and zoom are needed for both the dashboard and the
        # downstream photogrammetry code.
        telemetry["camera_sensor_width"] = self.SENSOR_WIDTH_MM
        telemetry["camera_sensor_height"] = self.SENSOR_HEIGHT_MM
        telemetry["camera_sensor_width_mm"] = self.SENSOR_WIDTH_MM
        telemetry["camera_sensor_height_mm"] = self.SENSOR_HEIGHT_MM
        telemetry["camera_focal_length_base"] = self.FOCAL_LENGTH_EQ_MM
        telemetry["camera_focal_length_base_mm"] = self.FOCAL_LENGTH_EQ_MM

        zoom = self._safe_get_state(zoom_level)
        zoom_level_value = _number(zoom.get("level")) if zoom else None
        if zoom_level_value is None or zoom_level_value <= 0:
            zoom_level_value = 1.0
        effective_focal_length = self.FOCAL_LENGTH_EQ_MM * zoom_level_value
        telemetry["camera_zoom_level"] = zoom_level_value
        telemetry["camera_focal_length"] = effective_focal_length
        telemetry["camera_focal_length_mm"] = effective_focal_length
        if zoom:
            cam_id = zoom.get("cam_id")
            if isinstance(cam_id, int):
                telemetry["camera_id"] = cam_id

        try:
            h_fov_deg, v_fov_deg = _camera_fov_degrees(
                self.SENSOR_WIDTH_MM,
                self.SENSOR_HEIGHT_MM,
                effective_focal_length,
            )
        except ValueError:
            h_fov_deg, v_fov_deg = (None, None)
        else:
            telemetry["sensor_h_fov"] = h_fov_deg
            telemetry["sensor_v_fov"] = v_fov_deg
            telemetry["camera_h_fov_deg"] = h_fov_deg
            telemetry["camera_v_fov_deg"] = v_fov_deg

        gps_fix_state = self._safe_get_state(GPSFixStateChanged)
        gps_location = self._safe_get_state(GpsLocationChanged)
        position_state = self._safe_get_state(PositionChanged)
        satellites = self._safe_get_state(NumberOfSatelliteChanged)
        home = self._safe_get_state(HomeChanged)
        return_home = self._safe_get_state(NavigateHomeStateChanged)
        return_home_min_alt = self._safe_get_state(ReturnHomeMinAltitudeChanged)

        if satellites:
            satellite_count = satellites.get("numberOfSatellite")
            if isinstance(satellite_count, int):
                telemetry["position_satellites"] = satellite_count

        gps_lat_raw = _number(gps_location.get("latitude")) if gps_location else None
        gps_lon_raw = _number(gps_location.get("longitude")) if gps_location else None
        gps_alt_raw = _number(gps_location.get("altitude")) if gps_location else None
        if gps_location:
            telemetry["gps_location_latitude_raw"] = gps_lat_raw
            telemetry["gps_location_longitude_raw"] = gps_lon_raw
            telemetry["gps_location_altitude_msl_raw"] = gps_alt_raw
            lat_accuracy_m = _number(gps_location.get("latitude_accuracy"))
            lon_accuracy_m = _number(gps_location.get("longitude_accuracy"))
            alt_accuracy_m = _number(gps_location.get("altitude_accuracy"))
            telemetry["position_latitude_accuracy_m"] = (
                None if lat_accuracy_m is None or lat_accuracy_m < 0 else lat_accuracy_m
            )
            telemetry["position_longitude_accuracy_m"] = (
                None if lon_accuracy_m is None or lon_accuracy_m < 0 else lon_accuracy_m
            )
            telemetry["position_altitude_accuracy_m"] = (
                None if alt_accuracy_m is None or alt_accuracy_m < 0 else alt_accuracy_m
            )

        position_lat_raw = _number(position_state.get("latitude")) if position_state else None
        position_lon_raw = _number(position_state.get("longitude")) if position_state else None
        position_alt_raw = _number(position_state.get("altitude")) if position_state else None
        if position_state:
            telemetry["position_changed_latitude_raw"] = position_lat_raw
            telemetry["position_changed_longitude_raw"] = position_lon_raw
            telemetry["position_changed_altitude_msl_raw"] = position_alt_raw

        position_valid = False
        position_message = "default_coordinates"
        chosen_lat = None
        chosen_lon = None
        chosen_alt_msl = None
        for message_name, lat_value, lon_value, alt_value in (
            ("GpsLocationChanged", gps_lat_raw, gps_lon_raw, gps_alt_raw),
            ("PositionChanged", position_lat_raw, position_lon_raw, position_alt_raw),
        ):
            if _valid_lat_lon(lat_value, lon_value):
                position_valid = True
                position_message = message_name
                chosen_lat = lat_value
                chosen_lon = lon_value
                chosen_alt_msl = alt_value
                break
            if chosen_alt_msl is None and alt_value is not None:
                chosen_alt_msl = alt_value

        gps_fixed = (
            bool(gps_fix_state.get("fixed", 0))
            if gps_fix_state is not None
            else position_valid
        )
        telemetry["gps_fixed"] = gps_fixed
        telemetry["gps_fix"] = gps_fixed

        telemetry["position_valid"] = position_valid
        telemetry["position_is_default"] = not position_valid
        telemetry["position_source"] = "gps" if position_valid else "default"
        if not gps_fixed and not position_valid:
            position_message = "gps_fix_unavailable"
        telemetry["position_message"] = position_message
        telemetry["position_latitude"] = chosen_lat if position_valid else None
        telemetry["position_longitude"] = chosen_lon if position_valid else None
        telemetry["position_altitude_msl"] = chosen_alt_msl
        telemetry["platform_altitude_msl"] = chosen_alt_msl

        telemetry["latitude"] = chosen_lat if position_valid else DEFAULT_LATITUDE
        telemetry["longitude"] = chosen_lon if position_valid else DEFAULT_LONGITUDE
        telemetry["altitude"] = (
            _klv_safe_altitude_msl(chosen_alt_msl) or DEFAULT_ALTITUDE_MSL_M
        )

        if home:
            home_lat = _number(home.get("latitude"))
            home_lon = _number(home.get("longitude"))
            home_alt = _number(home.get("altitude"))
            if _valid_lat_lon(home_lat, home_lon):
                telemetry["home_latitude"] = home_lat
                telemetry["home_longitude"] = home_lon
            telemetry["home_altitude_msl"] = home_alt

        if return_home:
            telemetry["return_home_state"] = _enum_text(return_home.get("state"))
            telemetry["return_home_reason"] = _enum_text(return_home.get("reason"))

        if return_home_min_alt:
            telemetry["return_home_min_altitude_m"] = _number(return_home_min_alt.get("value"))
            telemetry["return_home_min_altitude_min_m"] = _number(
                return_home_min_alt.get("min")
            )
            telemetry["return_home_min_altitude_max_m"] = _number(
                return_home_min_alt.get("max")
            )

        altitude_takeoff = self._safe_get_state(AltitudeChanged)
        altitude_agl = self._safe_get_state(AltitudeAboveGroundChanged)
        altitude_takeoff_m = (
            _number(altitude_takeoff.get("altitude")) if altitude_takeoff else None
        )
        altitude_agl_m = _number(altitude_agl.get("altitude")) if altitude_agl else None
        telemetry["altitude_relative_takeoff_m"] = altitude_takeoff_m
        telemetry["altitude_takeoff_m"] = altitude_takeoff_m
        telemetry["altitude_agl"] = altitude_agl_m
        if altitude_agl_m is not None and chosen_alt_msl is not None:
            telemetry["ground_altitude_msl"] = chosen_alt_msl - altitude_agl_m

        attitude = self._safe_get_state(AttitudeChanged)
        if attitude:
            roll_rad = _number(attitude.get("roll"))
            pitch_rad = _number(attitude.get("pitch"))
            yaw_rad = _number(attitude.get("yaw"))
            telemetry["roll"] = roll_rad
            telemetry["pitch"] = pitch_rad
            telemetry["yaw"] = yaw_rad
            telemetry["roll_deg"] = None if roll_rad is None else math.degrees(roll_rad)
            telemetry["pitch_deg"] = None if pitch_rad is None else math.degrees(pitch_rad)
            telemetry["yaw_deg"] = None if yaw_rad is None else math.degrees(yaw_rad)
            telemetry["heading_deg"] = _normalize_heading_deg(yaw_rad)

        speed = self._safe_get_state(SpeedChanged)
        if speed:
            speed_x = _number(speed.get("speedX"))
            speed_y = _number(speed.get("speedY"))
            speed_z = _number(speed.get("speedZ"))
            telemetry["speed_x"] = speed_x
            telemetry["speed_y"] = speed_y
            telemetry["speed_z"] = speed_z
            if speed_x is not None and speed_y is not None:
                telemetry["speed_horizontal_mps"] = math.hypot(speed_x, speed_y)
            if None not in (speed_x, speed_y, speed_z):
                telemetry["speed_total_mps"] = math.sqrt(
                    speed_x * speed_x + speed_y * speed_y + speed_z * speed_z
                )

        air_speed = self._safe_get_state(AirSpeedChanged)
        if air_speed:
            telemetry["airspeed_mps"] = _number(air_speed.get("airSpeed"))

        wifi = self._safe_get_state(WifiSignalChanged)
        if wifi:
            telemetry["rssi_dbm"] = _number(wifi.get("rssi"))

        link_quality = self._safe_get_state(LinkSignalQuality)
        if link_quality:
            link_value = link_quality.get("value")
            if isinstance(link_value, int):
                telemetry["link_quality_bits"] = link_value
                telemetry["link_quality_level"] = link_value & 0x0F
                telemetry["link_quality_4g_interference"] = bool(link_value & (1 << 6))
                telemetry["link_quality_external_perturbation"] = bool(link_value & (1 << 7))

        flying_state = self._safe_get_state(FlyingStateChanged)
        if flying_state:
            telemetry["flying_state"] = _enum_text(flying_state.get("state"))

        alert_state = self._safe_get_state(AlertStateChanged)
        if alert_state:
            telemetry["alert_state"] = _enum_text(alert_state.get("state"))

        wind_state = self._safe_get_state(WindStateChanged)
        if wind_state:
            telemetry["wind_state"] = _enum_text(wind_state.get("state"))

        vibration = self._safe_get_state(VibrationLevelChanged)
        if vibration:
            telemetry["vibration_level"] = _enum_text(vibration.get("state"))

        heading_locked = self._safe_get_state(HeadingLockedStateChanged)
        if heading_locked:
            telemetry["heading_locked_state"] = _enum_text(heading_locked.get("state"))

        hovering_warning = self._safe_get_state(HoveringWarning)
        if hovering_warning:
            telemetry["hovering_warning_no_gps_too_dark"] = bool(
                hovering_warning.get("no_gps_too_dark", False)
            )
            telemetry["hovering_warning_no_gps_too_high"] = bool(
                hovering_warning.get("no_gps_too_high", False)
            )

        gatt = self._safe_get_state(GimbalAttitude)
        if gatt:
            gimbal_id = gatt.get("gimbal_id")
            if isinstance(gimbal_id, int):
                telemetry["gimbal_id"] = gimbal_id
            telemetry["gimbal_yaw_frame_of_reference"] = _enum_text(
                gatt.get("yaw_frame_of_reference")
            )
            telemetry["gimbal_pitch_frame_of_reference"] = _enum_text(
                gatt.get("pitch_frame_of_reference")
            )
            telemetry["gimbal_roll_frame_of_reference"] = _enum_text(
                gatt.get("roll_frame_of_reference")
            )
            telemetry["gimbal_yaw_abs"] = _number(gatt.get("yaw_absolute"))
            telemetry["gimbal_pitch_abs"] = _number(gatt.get("pitch_absolute"))
            telemetry["gimbal_roll_abs"] = _number(gatt.get("roll_absolute"))
            telemetry["gimbal_yaw_rel"] = _number(gatt.get("yaw_relative"))
            telemetry["gimbal_pitch_rel"] = _number(gatt.get("pitch_relative"))
            telemetry["gimbal_roll_rel"] = _number(gatt.get("roll_relative"))

        goff = self._safe_get_state(GimbalOffsets)
        if goff:
            telemetry["gimbal_offset_update_state"] = _enum_text(goff.get("update_state"))
            telemetry["gimbal_offset_min_yaw"] = _number(goff.get("min_bound_yaw"))
            telemetry["gimbal_offset_max_yaw"] = _number(goff.get("max_bound_yaw"))
            telemetry["gimbal_offset_yaw"] = _number(goff.get("current_yaw"))
            telemetry["gimbal_offset_min_pitch"] = _number(goff.get("min_bound_pitch"))
            telemetry["gimbal_offset_max_pitch"] = _number(goff.get("max_bound_pitch"))
            telemetry["gimbal_offset_pitch"] = _number(goff.get("current_pitch"))
            telemetry["gimbal_offset_min_roll"] = _number(goff.get("min_bound_roll"))
            telemetry["gimbal_offset_max_roll"] = _number(goff.get("max_bound_roll"))
            telemetry["gimbal_offset_roll"] = _number(goff.get("current_roll"))

        cam_align = self._safe_get_state(alignment_offsets)
        if cam_align:
            cam_align_id = cam_align.get("cam_id")
            if isinstance(cam_align_id, int):
                telemetry["camera_alignment_cam_id"] = cam_align_id
                telemetry.setdefault("camera_id", cam_align_id)
            telemetry["cam_align_min_yaw"] = _number(cam_align.get("min_bound_yaw"))
            telemetry["cam_align_max_yaw"] = _number(cam_align.get("max_bound_yaw"))
            telemetry["cam_align_yaw"] = _number(cam_align.get("current_yaw"))
            telemetry["cam_align_min_pitch"] = _number(cam_align.get("min_bound_pitch"))
            telemetry["cam_align_max_pitch"] = _number(cam_align.get("max_bound_pitch"))
            telemetry["cam_align_pitch"] = _number(cam_align.get("current_pitch"))
            telemetry["cam_align_min_roll"] = _number(cam_align.get("min_bound_roll"))
            telemetry["cam_align_max_roll"] = _number(cam_align.get("max_bound_roll"))
            telemetry["cam_align_roll"] = _number(cam_align.get("current_roll"))

        recording = self._safe_get_state(recording_state)
        if recording:
            recording_cam_id = recording.get("cam_id")
            if isinstance(recording_cam_id, int):
                telemetry["camera_recording_cam_id"] = recording_cam_id
                telemetry.setdefault("camera_id", recording_cam_id)
            telemetry["camera_recording_available"] = _enum_text(recording.get("available"))
            telemetry["camera_recording_state"] = _enum_text(recording.get("state"))
            start_timestamp_ms = _number(recording.get("start_timestamp"))
            telemetry["camera_recording_start_timestamp_ms"] = start_timestamp_ms
            if start_timestamp_ms is not None and start_timestamp_ms > 0:
                telemetry["camera_recording_start_time"] = datetime.fromtimestamp(
                    start_timestamp_ms / 1000.0,
                    tz=UTC,
                ).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        storage = self._safe_get_state(MassStorageInfoRemainingListChanged)
        if storage:
            telemetry["storage_free_space_mb"] = _number(storage.get("free_space"))
            telemetry["storage_recording_time_remaining_min"] = _number(storage.get("rec_time"))
            telemetry["storage_photo_remaining"] = _number(storage.get("photo_remaining"))

        product_name = self._safe_get_state(ProductNameChanged)
        if product_name:
            telemetry["product_name"] = product_name.get("name")

        product_version = self._safe_get_state(ProductVersionChanged)
        if product_version:
            telemetry["product_software_version"] = product_version.get("software")
            telemetry["product_hardware_version"] = product_version.get("hardware")

        motor_status = self._safe_get_state(MotorFlightsStatusChanged)
        if motor_status:
            telemetry["motor_total_flights"] = motor_status.get("nbFlights")
            telemetry["motor_last_flight_duration_s"] = motor_status.get("lastFlightDuration")
            telemetry["motor_total_flight_duration_s"] = motor_status.get(
                "totalFlightDuration"
            )

        return telemetry
    
    def forward_telemetry(self, telemetry):
        """
        Forward telemetry data via UDP as KLV (MISB 0601) binary format.
        
        Args:
            telemetry: Dictionary containing telemetry data
        """
        if not self.udp_socket:
            return

        try:
            # Convert ISO timestamp to Unix timestamp in microseconds
            try:
                ts_str = telemetry.get("timestamp", _utc_now_iso())
                # Handle both with and without 'Z' suffix
                ts_str = ts_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str)
                telemetry["timestamp_us"] = int(dt.timestamp() * 1_000_000)
            except Exception as e:
                self.logger.warning(f"Error parsing timestamp: {e}")
                telemetry["timestamp_us"] = None

            # Encode telemetry to KLV using our custom encoder
            klv_packet = encode_telemetry_to_klv(telemetry)

            if not klv_packet:
                self.send_errors += 1
                self.logger.error(f"✗ Failed to encode KLV packet. Telemetry: {telemetry}")
                return

            # Debug: log first few KLV packets
            if self.packets_sent < 2:
                gps_status = (
                    "GPS VALID"
                    if telemetry.get("position_valid")
                    else "NO VALID GPS (default KLV coordinates)"
                )
                self.logger.info(
                    f"DEBUG: KLV packet #{self.packets_sent + 1} - "
                    f"{len(klv_packet)} bytes - {gps_status}"
                )
                if telemetry.get("position_valid"):
                    self.logger.info(
                        f"  GPS: Lat={telemetry.get('position_latitude', 'N/A')}, "
                        f"Lon={telemetry.get('position_longitude', 'N/A')}, "
                        f"AltMSL={telemetry.get('position_altitude_msl', 'N/A')}m"
                    )
                roll_deg = telemetry.get("roll_deg")
                pitch_deg = telemetry.get("pitch_deg")
                yaw_deg = telemetry.get("yaw_deg")
                self.logger.info(
                    "  Orientation: Roll=%s, Pitch=%s, Yaw=%s",
                    "N/A" if roll_deg is None else f"{roll_deg:.3f}°",
                    "N/A" if pitch_deg is None else f"{pitch_deg:.3f}°",
                    "N/A" if yaw_deg is None else f"{yaw_deg:.3f}°",
                )

            # Send raw KLV packet via UDP to localhost for GStreamer
            self.udp_socket.sendto(klv_packet, (self.local_klv_host, self.local_klv_port))
            self.packets_sent += 1

            # Debug: log first few KLV packets
            if self.packets_sent <= 3:
                self.logger.info(f"Sent KLV packet #{self.packets_sent}: {len(klv_packet)} bytes")

        except Exception as e:
            self.send_errors += 1
            self.logger.error(f"✗ Error encoding or sending KLV packet #{self.packets_sent}: {e}")
    
    def log_performance_stats(self):
        """Log performance statistics."""
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
            self.last_stats_time = current_time
            return
        
        # Check if it's time to report stats
        if current_time - self.last_stats_time >= self.stats_interval:
            elapsed = current_time - self.start_time
            actual_fps = self.telemetry_count / elapsed if elapsed > 0 else 0
            
            # Calculate loop time statistics
            if self.loop_times:
                avg_loop_time = sum(self.loop_times) / len(self.loop_times)
                min_loop_time = min(self.loop_times)
                max_loop_time = max(self.loop_times)
                
                # Check if we're meeting target FPS
                fps_ratio = (actual_fps / self.fps) * 100 if self.fps > 0 else 0
                
                status = "✓" if fps_ratio >= 95 else "⚠" if fps_ratio >= 80 else "✗"
                
                # Build performance message
                perf_msg = (
                    f"{status} PERFORMANCE: "
                    f"Target={self.fps:.1f} fps, Actual={actual_fps:.2f} fps ({fps_ratio:.1f}%) | "
                    f"Loop: avg={avg_loop_time*1000:.2f}ms, min={min_loop_time*1000:.2f}ms, max={max_loop_time*1000:.2f}ms | "
                    f"Count={self.telemetry_count} | "
                    f"KLV: sent={self.packets_sent}, errors={self.send_errors}"
                )
                
                self.logger.info(perf_msg)
                
                # Warn if we're falling behind
                if fps_ratio < 95:
                    self.logger.warning(
                        f"Telemetry forwarding is running at {fps_ratio:.1f}% of target FPS! "
                        f"Target: {self.fps} fps, Actual: {actual_fps:.2f} fps"
                    )
            
            self.last_stats_time = current_time
    
    def run(self):
        """Main thread execution loop with precise timing."""
        self.logger.info(f"Started - Target FPS: {self.fps} Hz (interval: {self.interval*1000:.2f}ms)")
        self.running = True
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        
        # Use target time instead of sleep-based timing for better precision
        next_frame_time = self.start_time
        
        while self.running:
            try:
                loop_start = time.time()
                
                # Get telemetry data
                telemetry = self.get_telemetry_data()
                self.telemetry_count += 1
                
                # Forward telemetry
                self.forward_telemetry(telemetry)
                
                # Track loop time
                loop_time = time.time() - loop_start
                self.loop_times.append(loop_time)
                if len(self.loop_times) > self.max_loop_times:
                    self.loop_times.pop(0)
                
                # Log performance stats periodically
                self.log_performance_stats()
                
                # Calculate next target time
                next_frame_time += self.interval
                current_time = time.time()
                sleep_time = next_frame_time - current_time
                
                if sleep_time > 0:
                    # Sleep until next frame time
                    time.sleep(sleep_time)
                else:
                    # We're falling behind - reset timing to avoid spiral
                    if sleep_time < -self.interval:
                        self.logger.warning(
                            f"Fell behind by {-sleep_time*1000:.2f}ms - resetting timing"
                        )
                        next_frame_time = time.time()
                    
                    # Warn if we can't keep up
                    if self.telemetry_count % self.fps == 0:  # Once per second
                        self.logger.warning(
                            f"Cannot maintain {self.fps} fps - loop took {loop_time*1000:.2f}ms "
                            f"(target: {self.interval*1000:.2f}ms)"
                        )
                
            except KeyboardInterrupt:
                self.logger.info("⚠ Interrupted by user")
                self.running = False
                break
            except Exception as e:
                self.logger.error(f"Error in telemetry loop: {e}")
                next_frame_time = time.time() + self.interval
                time.sleep(self.interval)
        
        # Final stats
        if self.start_time:
            total_elapsed = time.time() - self.start_time
            final_fps = self.telemetry_count / total_elapsed if total_elapsed > 0 else 0
            self.logger.info(
                f"Stopped - Forwarded {self.telemetry_count} telemetry packets | "
                f"Average FPS: {final_fps:.2f} (target: {self.fps})"
            )
    
    def stop(self):
        """Stop the telemetry forwarder and cleanup resources."""
        self.running = False
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass
        self.logger.info("Stopped")
