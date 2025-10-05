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
        
        # Check if GPS is valid before adding GPS data
        gps_fixed = telemetry.get('gps_fixed', False)
        
        # Add GPS data only if GPS is fixed and values are in valid ranges
        if gps_fixed:
            if 'latitude' in telemetry and telemetry['latitude'] is not None:
                lat = float(telemetry['latitude'])
                if -90.0 <= lat <= 90.0:
                    encoder.add_latitude(lat)
            
            if 'longitude' in telemetry and telemetry['longitude'] is not None:
                lon = float(telemetry['longitude'])
                if -180.0 <= lon <= 180.0:
                    encoder.add_longitude(lon)
            
            if 'altitude' in telemetry and telemetry['altitude'] is not None:
                alt = float(telemetry['altitude'])
                if 0 <= alt < 6553.5:  # Max value for 2-byte scaled by 10
                    encoder.add_altitude(alt)
        
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
        
        # Pack and return (even if empty - will contain just the KLV header)
        return encoder.pack()
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"KLV encoding error: {e}", exc_info=True)
        return None

