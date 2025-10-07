"""
KLV Encoder - Simple MISB 0601 KLV encoder for telemetry data

Implements a minimal MISB 0601 KLV encoder without external dependencies.
KLV (Key-Length-Value) is a binary encoding standard used for metadata.
"""

import struct
from typing import Dict, Any, Optional


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
    TAG_SENSOR_H_FOV = 18       # Sensor horizontal field of view (degrees)
    TAG_SENSOR_V_FOV = 19       # Sensor vertical field of view (degrees)
    TAG_SENSOR_REL_ROLL = 21    # Sensor relative roll angle (degrees)
    TAG_SENSOR_REL_PITCH = 22   # Sensor relative elevation angle (degrees)
    TAG_SENSOR_REL_YAW = 23     # Sensor relative azimuth angle (degrees)
    TAG_SENSOR_WIDTH = 102      # Sensor width (millimeters)
    TAG_SENSOR_HEIGHT = 103     # Sensor height (millimeters)
    TAG_FOCAL_LENGTH = 104      # Focal length (millimeters)
    
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
            # Each item: Tag (1 byte) + Length (1 byte) + Value
            lds_value.append(tag)
            lds_value.append(len(value))
            lds_value.extend(value)
        
        # Build complete KLV packet: Key + Length + Value
        klv_packet = bytearray()
        klv_packet.extend(self.MISB_0601_KEY)
        klv_packet.extend(self._encode_ber_length(len(lds_value)))
        klv_packet.extend(lds_value)
        
        return bytes(klv_packet)


def encode_telemetry_to_klv(telemetry: Dict[str, Any]) -> Optional[bytes]:
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
        
        # --- ALWAYS ADD GPS DATA (using defaults if not available) ---
        # Add latitude (always present, uses default if GPS not fixed)
        if 'latitude' in telemetry and telemetry['latitude'] is not None:
            lat = float(telemetry['latitude'])
            if -90.0 <= lat <= 90.0:
                encoder.add_latitude(lat)
        
        # Add longitude (always present, uses default if GPS not fixed)
        if 'longitude' in telemetry and telemetry['longitude'] is not None:
            lon = float(telemetry['longitude'])
            if -180.0 <= lon <= 180.0:
                encoder.add_longitude(lon)
        
        # Add altitude (use 10m default if not available)
        if 'altitude' in telemetry and telemetry['altitude'] is not None:
            alt = float(telemetry['altitude'])
            if 0 <= alt < 6553.5:  # Max value for 2-byte scaled by 10
                encoder.add_altitude(alt)
        else:
            # Default altitude: 10 meters
            encoder.add_altitude(10.0)
        
        # Add orientation data (always available even without GPS)
        if 'roll' in telemetry and telemetry['roll'] is not None:
            roll = float(telemetry['roll'])
            if -180.0 <= roll <= 180.0:
                encoder.add_roll(roll)
        
        if 'pitch' in telemetry and telemetry['pitch'] is not None:
            pitch = float(telemetry['pitch'])
            if -90.0 <= pitch <= 90.0:
                encoder.add_pitch(pitch)
        
        if 'yaw' in telemetry and telemetry['yaw'] is not None:
            yaw = float(telemetry['yaw'])
            # Normalize yaw to 0-360 range if needed
            if yaw < 0:
                yaw = yaw + 360.0
            if 0 <= yaw <= 360.0:
                encoder.add_heading(yaw)
        
        # --- NEW: ADD CAMERA SENSOR PARAMETERS (static data) ---
        if 'camera_sensor_width' in telemetry and telemetry['camera_sensor_width'] is not None:
            encoder.add_sensor_width(float(telemetry['camera_sensor_width']))
        
        if 'camera_sensor_height' in telemetry and telemetry['camera_sensor_height'] is not None:
            encoder.add_sensor_height(float(telemetry['camera_sensor_height']))
        
        if 'camera_focal_length' in telemetry and telemetry['camera_focal_length'] is not None:
            encoder.add_focal_length(float(telemetry['camera_focal_length']))
        
        # --- NEW: ADD GIMBAL STATE (absolute orientation) ---
        # These represent the camera/sensor orientation relative to the platform
        if 'gimbal_yaw_abs' in telemetry and telemetry['gimbal_yaw_abs'] is not None:
            encoder.add_sensor_relative_yaw(float(telemetry['gimbal_yaw_abs']))
        
        if 'gimbal_pitch_abs' in telemetry and telemetry['gimbal_pitch_abs'] is not None:
            encoder.add_sensor_relative_pitch(float(telemetry['gimbal_pitch_abs']))
        
        if 'gimbal_roll_abs' in telemetry and telemetry['gimbal_roll_abs'] is not None:
            encoder.add_sensor_relative_roll(float(telemetry['gimbal_roll_abs']))
        
        # Note: Gimbal offsets and camera alignment offsets are included in telemetry
        # but may need to be applied to compute final orientation rather than
        # transmitted separately. They are available in the telemetry dict if needed.
        
        # Pack and return (even if empty - will contain just the KLV header)
        return encoder.pack()
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"KLV encoding error: {e}", exc_info=True)
        return None

