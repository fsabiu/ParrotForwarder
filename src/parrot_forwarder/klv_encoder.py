"""
KLV Encoder - Simple MISB 0601 KLV encoder for telemetry data

Implements a minimal MISB 0601 KLV encoder without external dependencies.
KLV (Key-Length-Value) is a binary encoding standard used for metadata.
"""

import json
import math
import struct
from typing import Dict, Any, Optional

AION_TELEMETRY_CONTRACT_VERSION = "aion.parrot.telemetry.v1"
UNKNOWN_SOURCE_ID = "parrot_anafi_unknown"


def _valid_lat_lon(latitude: object, longitude: object) -> bool:
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return False
    lat = float(latitude)
    lon = float(longitude)
    if not math.isfinite(lat) or not math.isfinite(lon):
        return False
    if lat == 500.0 or lon == 500.0:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _safe_source_id(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        return UNKNOWN_SOURCE_ID
    chars: list[str] = []
    for ch in name.strip().lower():
        if ch.isalnum():
            chars.append(ch)
        elif ch in "-_ .":
            chars.append("_")
    source_id = "".join(chars).strip("_")
    while "__" in source_id:
        source_id = source_id.replace("__", "_")
    return source_id or UNKNOWN_SOURCE_ID


class MISB0601Encoder:
    """
    Simple MISB 0601 KLV encoder for drone telemetry.
    
    Encodes telemetry data into MISB 0601 compliant KLV packets.
    """
    
    # MISB 0601 Universal Key (16 bytes)
    # 06.0E.2B.34.02.0B.01.01.0E.01.03.01.01.00.00.00
    MISB_0601_KEY = bytes([
        0x06, 0x0E, 0x2B, 0x34, 0x02, 0x0B, 0x01, 0x01,
        0x0E, 0x01, 0x03, 0x01, 0x01, 0x00, 0x00, 0x00
    ])
    
    # MISB 0601 Tag numbers
    TAG_UNIX_TIMESTAMP = 2      # Unix timestamp (microseconds)
    TAG_SENSOR_LATITUDE = 13    # Sensor latitude (degrees)
    TAG_SENSOR_LONGITUDE = 14   # Sensor longitude (degrees)
    TAG_SENSOR_TRUE_ALT = 15    # Sensor true altitude (meters)
    TAG_PLATFORM_ROLL = 5       # Platform roll angle (degrees)
    TAG_PLATFORM_PITCH = 6      # Platform pitch angle (degrees)
    TAG_PLATFORM_HEADING = 7    # Platform heading angle (degrees)
    
    # --- NEW: MISB 0601 Tags for Gimbal and Camera ---
    TAG_SENSOR_H_FOV = 16       # Sensor horizontal field of view (degrees)
    TAG_SENSOR_V_FOV = 17       # Sensor vertical field of view (degrees)
    TAG_SENSOR_REL_ROLL = 21    # Sensor relative roll angle (degrees)
    TAG_SENSOR_REL_PITCH = 22   # Sensor relative elevation angle (degrees)
    TAG_SENSOR_REL_YAW = 23     # Sensor relative azimuth angle (degrees)
    TAG_SENSOR_WIDTH = 102      # Sensor width (millimeters)
    TAG_SENSOR_HEIGHT = 103     # Sensor height (millimeters)
    TAG_FOCAL_LENGTH = 104      # Focal length (millimeters)
    TAG_AION_TELEMETRY_JSON = 120  # AION full telemetry JSON extension
    
    # Custom tags for gimbal absolute angles (vendor-specific 105-110)
    TAG_GIMBAL_ABS_YAW = 105    # Gimbal absolute yaw (degrees)
    TAG_GIMBAL_ABS_PITCH = 106  # Gimbal absolute pitch (degrees)
    TAG_GIMBAL_ABS_ROLL = 107   # Gimbal absolute roll (degrees)
    
    def __init__(self):
        """Initialize the MISB 0601 encoder."""
        self.items = []
    
    def clear(self):
        """Clear all encoded items."""
        self.items = []
    
    def add_timestamp(self, timestamp_us: int):
        """
        Add Unix timestamp in microseconds.
        
        Args:
            timestamp_us: Unix timestamp in microseconds
        """
        # Encode as 8-byte unsigned integer
        value = struct.pack('>Q', timestamp_us)
        self.items.append((self.TAG_UNIX_TIMESTAMP, value))
    
    def add_latitude(self, latitude: float):
        """
        Add sensor latitude in degrees.
        
        Args:
            latitude: Latitude in degrees (-90 to +90)
        """
        # Validate latitude range
        if not (-90.0 <= latitude <= 90.0):
            raise ValueError(f"Invalid latitude: {latitude} (must be -90 to +90)")
        
        # Encode as 4-byte signed integer (scaled by 1e7)
        scaled = int(latitude * 1e7)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_SENSOR_LATITUDE, value))
    
    def add_longitude(self, longitude: float):
        """
        Add sensor longitude in degrees.
        
        Args:
            longitude: Longitude in degrees (-180 to +180)
        """
        # Validate longitude range
        if not (-180.0 <= longitude <= 180.0):
            raise ValueError(f"Invalid longitude: {longitude} (must be -180 to +180)")
        
        # Encode as 4-byte signed integer (scaled by 1e7)
        scaled = int(longitude * 1e7)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_SENSOR_LONGITUDE, value))
    
    def add_altitude(self, altitude: float):
        """
        Add sensor true altitude in meters.
        
        Args:
            altitude: Altitude in meters above MSL
        """
        # Encode as 2-byte unsigned integer (scaled by 10)
        scaled = int(altitude * 10)
        value = struct.pack('>H', scaled & 0xFFFF)
        self.items.append((self.TAG_SENSOR_TRUE_ALT, value))
    
    def add_roll(self, roll: float):
        """
        Add platform roll angle in degrees.
        
        Args:
            roll: Roll angle in degrees (-180 to +180)
        """
        # Encode as 2-byte signed integer (scaled by 100)
        scaled = int(roll * 100)
        value = struct.pack('>h', scaled)
        self.items.append((self.TAG_PLATFORM_ROLL, value))
    
    def add_pitch(self, pitch: float):
        """
        Add platform pitch angle in degrees.
        
        Args:
            pitch: Pitch angle in degrees (-90 to +90)
        """
        # Encode as 2-byte signed integer (scaled by 100)
        scaled = int(pitch * 100)
        value = struct.pack('>h', scaled)
        self.items.append((self.TAG_PLATFORM_PITCH, value))
    
    def add_heading(self, heading: float):
        """
        Add platform heading angle in degrees.
        
        Args:
            heading: Heading angle in degrees (0 to 360)
        """
        # Encode as 2-byte unsigned integer (scaled by 100)
        scaled = int(heading * 100)
        value = struct.pack('>H', scaled & 0xFFFF)
        self.items.append((self.TAG_PLATFORM_HEADING, value))
    
    # --- NEW: METHODS FOR GIMBAL AND CAMERA PARAMETERS ---
    
    def add_sensor_relative_roll(self, roll: float):
        """
        Add sensor relative roll angle in degrees (gimbal roll).
        
        Args:
            roll: Sensor relative roll angle in degrees (-180 to +180)
        """
        # Encode as 4-byte signed integer (scaled by 1e6)
        scaled = int(roll * 1e6)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_SENSOR_REL_ROLL, value))
    
    def add_sensor_relative_pitch(self, pitch: float):
        """
        Add sensor relative pitch/elevation angle in degrees (gimbal pitch).
        
        Args:
            pitch: Sensor relative pitch angle in degrees (-90 to +90)
        """
        # Encode as 4-byte signed integer (scaled by 1e6)
        scaled = int(pitch * 1e6)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_SENSOR_REL_PITCH, value))
    
    def add_sensor_relative_yaw(self, yaw: float):
        """
        Add sensor relative azimuth/yaw angle in degrees (gimbal yaw).
        
        Args:
            yaw: Sensor relative yaw angle in degrees (-180 to +180)
        """
        # Encode as 4-byte signed integer (scaled by 1e6)
        scaled = int(yaw * 1e6)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_SENSOR_REL_YAW, value))
    
    def add_sensor_h_fov(self, fov: float):
        """
        Add sensor horizontal field of view in degrees.
        
        Args:
            fov: Horizontal field of view in degrees (0 to 180)
        """
        # Encode as 2-byte unsigned integer (scaled by 100)
        scaled = int(fov * 100)
        value = struct.pack('>H', scaled & 0xFFFF)
        self.items.append((self.TAG_SENSOR_H_FOV, value))
    
    def add_sensor_v_fov(self, fov: float):
        """
        Add sensor vertical field of view in degrees.
        
        Args:
            fov: Vertical field of view in degrees (0 to 180)
        """
        # Encode as 2-byte unsigned integer (scaled by 100)
        scaled = int(fov * 100)
        value = struct.pack('>H', scaled & 0xFFFF)
        self.items.append((self.TAG_SENSOR_V_FOV, value))
    
    def add_sensor_width(self, width: float):
        """
        Add sensor width in millimeters.
        
        Args:
            width: Sensor width in millimeters
        """
        # Encode as 4-byte float
        value = struct.pack('>f', width)
        self.items.append((self.TAG_SENSOR_WIDTH, value))
    
    def add_sensor_height(self, height: float):
        """
        Add sensor height in millimeters.
        
        Args:
            height: Sensor height in millimeters
        """
        # Encode as 4-byte float
        value = struct.pack('>f', height)
        self.items.append((self.TAG_SENSOR_HEIGHT, value))
    
    def add_focal_length(self, focal_length: float):
        """
        Add focal length in millimeters.
        
        Args:
            focal_length: Focal length in millimeters
        """
        # Encode as 4-byte float
        value = struct.pack('>f', focal_length)
        self.items.append((self.TAG_FOCAL_LENGTH, value))
    
    def add_gimbal_absolute_yaw(self, yaw: float):
        """
        Add gimbal absolute yaw angle in degrees.
        
        Args:
            yaw: Gimbal absolute yaw in degrees (-180 to +180)
        """
        # Encode as 4-byte signed integer (scaled by 1e6)
        scaled = int(yaw * 1e6)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_GIMBAL_ABS_YAW, value))
    
    def add_gimbal_absolute_pitch(self, pitch: float):
        """
        Add gimbal absolute pitch angle in degrees.
        
        Args:
            pitch: Gimbal absolute pitch in degrees (-90 to +90)
        """
        # Encode as 4-byte signed integer (scaled by 1e6)
        scaled = int(pitch * 1e6)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_GIMBAL_ABS_PITCH, value))
    
    def add_gimbal_absolute_roll(self, roll: float):
        """
        Add gimbal absolute roll angle in degrees.
        
        Args:
            roll: Gimbal absolute roll in degrees (-180 to +180)
        """
        # Encode as 4-byte signed integer (scaled by 1e6)
        scaled = int(roll * 1e6)
        value = struct.pack('>i', scaled)
        self.items.append((self.TAG_GIMBAL_ABS_ROLL, value))

    def add_aion_telemetry_json(self, payload: dict[str, Any]):
        """
        Add the AION full telemetry JSON extension.

        Standard MISB 0601 tags remain the stable geolocation core. This
        project-specific tag carries every ParrotForwarder real-time field so
        the detector can consume the complete contract without waiting for new
        one-off binary tags for every SDK value.
        """
        value = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        self.items.append((self.TAG_AION_TELEMETRY_JSON, value))
    
    def _encode_ber_length(self, length: int) -> bytes:
        """
        Encode length using BER (Basic Encoding Rules).
        
        Args:
            length: Length value to encode
            
        Returns:
            BER encoded length bytes
        """
        if length < 128:
            # Short form: single byte
            return bytes([length])
        elif length < 256:
            # Long form: 1 byte length
            return bytes([0x81, length])
        elif length < 65536:
            # Long form: 2 byte length
            return bytes([0x82]) + struct.pack('>H', length)
        else:
            # Long form: 4 byte length
            return bytes([0x84]) + struct.pack('>I', length)
    
    def pack(self) -> bytes:
        """
        Pack all items into a complete MISB 0601 KLV packet.
        
        Returns:
            Complete KLV packet as bytes
        """
        # Build the Local Data Set (LDS) value
        lds_value = bytearray()
        
        for tag, value in self.items:
            # Each item: Tag (1 byte) + BER Length + Value. Most fields fit in
            # the historical one-byte length; the AION JSON extension can be
            # larger, so item lengths use BER as well.
            lds_value.append(tag)
            lds_value.extend(self._encode_ber_length(len(value)))
            lds_value.extend(value)
        
        # Build complete KLV packet: Key + Length + Value
        klv_packet = bytearray()
        klv_packet.extend(self.MISB_0601_KEY)
        klv_packet.extend(self._encode_ber_length(len(lds_value)))
        klv_packet.extend(lds_value)
        
        return bytes(klv_packet)


def _build_aion_telemetry_payload(
    telemetry: Dict[str, Any],
    *,
    include_raw_sdk_state: bool = True,
) -> dict[str, Any]:
    source_name = telemetry.get("source_name") or telemetry.get("product_name") or UNKNOWN_SOURCE_ID
    source_id = telemetry.get("source_id") or _safe_source_id(source_name)
    payload_telemetry = dict(telemetry)
    if not include_raw_sdk_state:
        payload_telemetry.pop("olympe_state", None)
        payload_telemetry.pop("olympe_event_state", None)
    return {
        "contract_version": AION_TELEMETRY_CONTRACT_VERSION,
        "source": "parrot_forwarder",
        "source_id": source_id,
        "source_name": source_name,
        "timestamp": telemetry.get("timestamp"),
        "timestamp_us": telemetry.get("timestamp_us"),
        "sequence": telemetry.get("sequence"),
        "telemetry": payload_telemetry,
    }


def encode_telemetry_to_klv(
    telemetry: Dict[str, Any],
    *,
    include_raw_sdk_state: bool = True,
) -> Optional[bytes]:
    """
    Encode telemetry dictionary into MISB 0601 KLV packet.
    
    Args:
        telemetry: Dictionary containing telemetry data
        
    Returns:
        KLV packet as bytes, or None if encoding fails
    """
    try:
        encoder = MISB0601Encoder()
        
        # Add timestamp
        if 'timestamp_us' in telemetry and telemetry['timestamp_us'] is not None:
            encoder.add_timestamp(telemetry['timestamp_us'])
        
        position_valid = telemetry.get("position_valid")
        encode_position = position_valid is not False and _valid_lat_lon(
            telemetry.get("latitude"),
            telemetry.get("longitude"),
        )

        if encode_position and 'latitude' in telemetry and telemetry['latitude'] is not None:
            lat = float(telemetry['latitude'])
            encoder.add_latitude(lat)
        
        if encode_position and 'longitude' in telemetry and telemetry['longitude'] is not None:
            lon = float(telemetry['longitude'])
            encoder.add_longitude(lon)
        
        if encode_position and 'altitude' in telemetry and telemetry['altitude'] is not None:
            alt = float(telemetry['altitude'])
            if 0 <= alt < 6553.5:  # Max value for 2-byte scaled by 10
                encoder.add_altitude(alt)
        
        # Add orientation data (platform attitude from AttitudeChanged is in RADIANS)
        # Convert to degrees for KLV encoding (MISB 0601 expects degrees)
        if 'roll' in telemetry and telemetry['roll'] is not None:
            roll_rad = float(telemetry['roll'])
            roll_deg = math.degrees(roll_rad)
            if -180.0 <= roll_deg <= 180.0:
                encoder.add_roll(roll_deg)
        
        if 'pitch' in telemetry and telemetry['pitch'] is not None:
            pitch_rad = float(telemetry['pitch'])
            pitch_deg = math.degrees(pitch_rad)
            if -90.0 <= pitch_deg <= 90.0:
                encoder.add_pitch(pitch_deg)
        
        if 'yaw' in telemetry and telemetry['yaw'] is not None:
            yaw_rad = float(telemetry['yaw'])
            yaw_deg = math.degrees(yaw_rad)
            # Normalize yaw to 0-360 range if needed
            if yaw_deg < 0:
                yaw_deg = yaw_deg + 360.0
            if 0 <= yaw_deg <= 360.0:
                encoder.add_heading(yaw_deg)
        
        # --- NEW: ADD CAMERA SENSOR PARAMETERS (static data) ---
        sensor_width = telemetry.get('camera_sensor_width', telemetry.get('camera_sensor_width_mm'))
        if sensor_width is not None:
            encoder.add_sensor_width(float(sensor_width))

        sensor_height = telemetry.get('camera_sensor_height', telemetry.get('camera_sensor_height_mm'))
        if sensor_height is not None:
            encoder.add_sensor_height(float(sensor_height))

        focal_length = telemetry.get('camera_focal_length', telemetry.get('camera_focal_length_mm'))
        if focal_length is not None:
            encoder.add_focal_length(float(focal_length))

        sensor_h_fov = telemetry.get('sensor_h_fov', telemetry.get('camera_h_fov_deg'))
        if sensor_h_fov is not None:
            encoder.add_sensor_h_fov(float(sensor_h_fov))

        sensor_v_fov = telemetry.get('sensor_v_fov', telemetry.get('camera_v_fov_deg'))
        if sensor_v_fov is not None:
            encoder.add_sensor_v_fov(float(sensor_v_fov))
        
        # --- NEW: ADD GIMBAL STATE ---
        # Send BOTH relative and absolute gimbal angles
        
        # MISB 0601 Tags 21-23: Sensor Relative Angles (relative to platform/drone)
        if 'gimbal_yaw_rel' in telemetry and telemetry['gimbal_yaw_rel'] is not None:
            encoder.add_sensor_relative_yaw(float(telemetry['gimbal_yaw_rel']))
        
        if 'gimbal_pitch_rel' in telemetry and telemetry['gimbal_pitch_rel'] is not None:
            encoder.add_sensor_relative_pitch(float(telemetry['gimbal_pitch_rel']))
        
        if 'gimbal_roll_rel' in telemetry and telemetry['gimbal_roll_rel'] is not None:
            encoder.add_sensor_relative_roll(float(telemetry['gimbal_roll_rel']))
        
        # Custom Tags 105-107: Gimbal Absolute Angles (world frame reference)
        if 'gimbal_yaw_abs' in telemetry and telemetry['gimbal_yaw_abs'] is not None:
            encoder.add_gimbal_absolute_yaw(float(telemetry['gimbal_yaw_abs']))
        
        if 'gimbal_pitch_abs' in telemetry and telemetry['gimbal_pitch_abs'] is not None:
            encoder.add_gimbal_absolute_pitch(float(telemetry['gimbal_pitch_abs']))
        
        if 'gimbal_roll_abs' in telemetry and telemetry['gimbal_roll_abs'] is not None:
            encoder.add_gimbal_absolute_roll(float(telemetry['gimbal_roll_abs']))
        
        # Note: Gimbal offsets and camera alignment offsets are collected
        # in telemetry dict and available for post-processing or alternative uses

        encoder.add_aion_telemetry_json(
            _build_aion_telemetry_payload(
                telemetry,
                include_raw_sdk_state=include_raw_sdk_state,
            )
        )
        
        # Pack and return (even if empty - will contain just the KLV header)
        return encoder.pack()
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"KLV encoding error: {e}", exc_info=True)
        return None
