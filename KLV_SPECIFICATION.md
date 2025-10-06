# KLV Telemetry Specification for ParrotForwarder

## Overview

ParrotForwarder encodes drone telemetry using **MISB 0601** (Motion Imagery Standards Board Standard 0601) KLV (Key-Length-Value) format. This document provides complete specifications for implementing receivers/decoders.

---

## Should You Use the Encoder Class?

**No.** You need a **decoder** class on the receiver side.

- **Encoder** (`parrot_forwarder/klv_encoder.py`): Encodes telemetry → KLV binary (used by ParrotForwarder)
- **Decoder** (`tests/test_klv_receiver.py`): Decodes KLV binary → telemetry (used by receivers)

---

## KLV Packet Structure

### Overall Format

```
┌─────────────────────────────────────────────────┐
│ MISB 0601 KLV Packet                           │
├─────────────────────────────────────────────────┤
│ Universal Key (16 bytes)                        │
│ 06 0E 2B 34 02 0B 01 01 0E 01 03 01 01 00 00 00│
├─────────────────────────────────────────────────┤
│ Length (BER encoded, 1-5 bytes)                │
│ - If < 128: single byte                        │
│ - If ≥ 128: 0x81 + 1 byte, or 0x82 + 2 bytes  │
├─────────────────────────────────────────────────┤
│ Local Data Set (LDS) Value                     │
│ ┌─────────────────────────────────────────────┐│
│ │ Tag 1 | Length 1 | Value 1                  ││
│ ├─────────────────────────────────────────────┤│
│ │ Tag 2 | Length 2 | Value 2                  ││
│ ├─────────────────────────────────────────────┤│
│ │ ...                                         ││
│ ├─────────────────────────────────────────────┤│
│ │ Tag N | Length N | Value N                  ││
│ └─────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
```

---

## MISB 0601 Tag Definitions

ParrotForwarder encodes the following tags:

| Tag | Name | Size | Data Type | Scaling | Range | Description |
|-----|------|------|-----------|---------|-------|-------------|
| **2** | Unix Timestamp | 8 bytes | uint64 (big-endian) | Microseconds | 0 to 2^64-1 | Unix epoch timestamp in microseconds |
| **5** | Platform Roll | 2 bytes | int16 (big-endian) | ×100 | -18000 to +18000 | Roll angle in degrees ×100 (-180° to +180°) |
| **6** | Platform Pitch | 2 bytes | int16 (big-endian) | ×100 | -9000 to +9000 | Pitch angle in degrees ×100 (-90° to +90°) |
| **7** | Platform Heading | 2 bytes | uint16 (big-endian) | ×100 | 0 to 36000 | Heading/Yaw in degrees ×100 (0° to 360°) |
| **13** | Sensor Latitude | 4 bytes | int32 (big-endian) | ×10^7 | -900000000 to +900000000 | Latitude in degrees ×10^7 (-90° to +90°) |
| **14** | Sensor Longitude | 4 bytes | int32 (big-endian) | ×10^7 | -1800000000 to +1800000000 | Longitude in degrees ×10^7 (-180° to +180°) |
| **15** | Sensor True Altitude | 2 bytes | uint16 (big-endian) | ×10 | 0 to 65535 | Altitude MSL in meters ×10 (0m to 6553.5m) |

### Notes on Tags:
- **Tags 13, 14, 15** (GPS data): Only present when GPS is fixed
- **Tags 5, 6, 7** (Orientation): Always present (IMU data doesn't require GPS)
- **Tag 2** (Timestamp): Always present

---

## BER Length Encoding

**BER (Basic Encoding Rules)** is used to encode the length of the LDS value:

| Value Length | BER Encoding | Example |
|--------------|--------------|---------|
| 0-127 | Single byte | `0x2A` = 42 bytes |
| 128-255 | `0x81` + 1 byte | `0x81 0xFF` = 255 bytes |
| 256-65535 | `0x82` + 2 bytes | `0x82 0x01 0x00` = 256 bytes |
| 65536+ | `0x84` + 4 bytes | `0x84 0x00 0x01 0x00 0x00` = 65536 bytes |

---

## Decoding Algorithm

### Step-by-Step Process

```python
def decode_klv_packet(data: bytes) -> dict:
    """Decode MISB 0601 KLV packet."""
    
    # 1. Verify Universal Key (16 bytes)
    MISB_0601_KEY = bytes([
        0x06, 0x0E, 0x2B, 0x34, 0x02, 0x0B, 0x01, 0x01,
        0x0E, 0x01, 0x03, 0x01, 0x01, 0x00, 0x00, 0x00
    ])
    
    if not data.startswith(MISB_0601_KEY):
        raise ValueError("Invalid MISB 0601 key")
    
    offset = 16  # Skip key
    
    # 2. Parse BER Length
    length_byte = data[offset]
    offset += 1
    
    if length_byte < 128:
        # Short form
        value_length = length_byte
    elif length_byte == 0x81:
        # Long form: 1 byte
        value_length = data[offset]
        offset += 1
    elif length_byte == 0x82:
        # Long form: 2 bytes
        value_length = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
    elif length_byte == 0x84:
        # Long form: 4 bytes
        value_length = struct.unpack('>I', data[offset:offset+4])[0]
        offset += 4
    else:
        raise ValueError(f"Unsupported BER length: {length_byte}")
    
    # 3. Parse Local Data Set (LDS) items
    telemetry = {}
    end_offset = offset + value_length
    
    while offset < end_offset:
        # Read tag
        tag = data[offset]
        offset += 1
        
        # Read length
        item_length = data[offset]
        offset += 1
        
        # Read value
        value_bytes = data[offset:offset+item_length]
        offset += item_length
        
        # Decode based on tag
        if tag == 2:  # Unix Timestamp
            telemetry['timestamp_us'] = struct.unpack('>Q', value_bytes)[0]
            # Convert to datetime if needed:
            # telemetry['timestamp'] = datetime.fromtimestamp(
            #     telemetry['timestamp_us'] / 1_000_000
            # )
        
        elif tag == 5:  # Platform Roll
            scaled = struct.unpack('>h', value_bytes)[0]
            telemetry['roll'] = scaled / 100.0  # degrees
        
        elif tag == 6:  # Platform Pitch
            scaled = struct.unpack('>h', value_bytes)[0]
            telemetry['pitch'] = scaled / 100.0  # degrees
        
        elif tag == 7:  # Platform Heading
            scaled = struct.unpack('>H', value_bytes)[0]
            telemetry['heading'] = scaled / 100.0  # degrees
        
        elif tag == 13:  # Sensor Latitude
            scaled = struct.unpack('>i', value_bytes)[0]
            telemetry['latitude'] = scaled / 1e7  # degrees
        
        elif tag == 14:  # Sensor Longitude
            scaled = struct.unpack('>i', value_bytes)[0]
            telemetry['longitude'] = scaled / 1e7  # degrees
        
        elif tag == 15:  # Sensor True Altitude
            scaled = struct.unpack('>H', value_bytes)[0]
            telemetry['altitude'] = scaled / 10.0  # meters
    
    return telemetry
```

---

## Example KLV Packets

### Packet with GPS Fix (All Fields)

```
Hex Dump:
06 0E 2B 34 02 0B 01 01 0E 01 03 01 01 00 00 00  ← Universal Key
2D                                                  ← Length (45 bytes)
02 08 00 00 01 8C 5A 3B E1 40                      ← Tag 2: Timestamp
0D 04 02 3C AC 8E                                   ← Tag 13: Latitude (37.7749°)
0E 04 F8 98 31 9C                                   ← Tag 14: Longitude (-122.4194°)
0F 02 04 E3                                         ← Tag 15: Altitude (125.1m)
05 02 FF EC                                         ← Tag 5: Roll (-2.0°)
06 02 00 D2                                         ← Tag 6: Pitch (2.1°)
07 02 46 50                                         ← Tag 7: Heading (180.0°)

Decoded:
{
    'timestamp_us': 1696857346880,
    'latitude': 37.7749,
    'longitude': -122.4194,
    'altitude': 125.1,
    'roll': -2.0,
    'pitch': 2.1,
    'heading': 180.0
}
```

### Packet without GPS Fix (Orientation Only)

```
Hex Dump:
06 0E 2B 34 02 0B 01 01 0E 01 03 01 01 00 00 00  ← Universal Key
12                                                  ← Length (18 bytes)
02 08 00 00 01 8C 5A 3B E1 40                      ← Tag 2: Timestamp
05 02 FF EC                                         ← Tag 5: Roll (-2.0°)
06 02 00 D2                                         ← Tag 6: Pitch (2.1°)
07 02 46 50                                         ← Tag 7: Heading (180.0°)

Decoded:
{
    'timestamp_us': 1696857346880,
    'roll': -2.0,
    'pitch': 2.1,
    'heading': 180.0
}
```

---

## Receiver Implementation Options

### Option 1: Extract from MPEG-TS Stream (Recommended)

If you're receiving the unified SRT stream with video+KLV:

```python
import subprocess
import struct

def extract_klv_from_stream(srt_url):
    """Extract KLV stream using FFmpeg."""
    cmd = [
        'ffmpeg',
        '-i', srt_url,
        '-map', '0:d',  # Map data stream
        '-c', 'copy',
        '-f', 'data',
        'pipe:1'
    ]
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    
    while True:
        # Read KLV packet size (you may need to parse MPEG-TS PES)
        # This is simplified - actual MPEG-TS parsing is more complex
        klv_data = process.stdout.read(4096)
        if not klv_data:
            break
        
        telemetry = decode_klv_packet(klv_data)
        print(telemetry)
```

### Option 2: Direct UDP Receiver (Local Testing)

For testing the KLV stream directly before GStreamer muxing:

```python
import socket

def receive_klv_udp(port=12345):
    """Receive KLV packets directly from TelemetryForwarder."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', port))
    
    print(f"Listening for KLV on localhost:{port}")
    
    while True:
        data, addr = sock.recvfrom(65535)
        telemetry = decode_klv_packet(data)
        print(f"Telemetry: {telemetry}")
```

**Use the provided test script:**
```bash
python tests/test_klv_receiver.py --port 12345 --duration 60
```

### Option 3: GStreamer Application

For advanced integration with GStreamer:

```python
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

def on_klv_metadata(pad, info):
    """Callback for KLV metadata from GStreamer."""
    buffer = info.get_buffer()
    success, map_info = buffer.map(Gst.MapFlags.READ)
    
    if success:
        klv_data = map_info.data
        telemetry = decode_klv_packet(klv_data)
        print(f"Telemetry: {telemetry}")
        buffer.unmap(map_info)
    
    return Gst.PadProbeReturn.OK

# Attach probe to KLV stream pad
# (Full GStreamer application setup required)
```

---

## Testing Checklist

### 1. Test Local KLV Reception
```bash
# Terminal 1: Start ParrotForwarder
python ParrotForwarder.py

# Terminal 2: Test KLV receiver
python tests/test_klv_receiver.py --port 12345
```

**Expected Output:**
```
✓ Successfully bound to port 12345
Waiting for KLV packets...

Packet #1 received from 127.0.0.1:12345
Size: 45 bytes | Time since last: 0.100s
📦 KLV Packet Decoded:
  Timestamp: 2025-10-06T21:32:05.123456 UTC
  Latitude: 37.7749000°
  Longitude: -122.4194000°
  Altitude: 125.10 m
  Roll: -2.00°
  Pitch: 2.10°
  Heading: 180.00°
```

### 2. Test Unified Stream
```bash
# Check stream structure
ffprobe srt://100.105.188.84:8890

# Expected output:
# Stream #0:0: Video: h264, 1280x720, 29.97 fps
# Stream #0:1: Data: klv (KLVA / 0x41564C4B)
```

### 3. Extract KLV from Recording
```bash
# Record 10 seconds
ffmpeg -i srt://100.105.188.84:8890 -c copy -map 0:v -map 0:d -t 10 test.ts

# Extract KLV stream
ffmpeg -i test.ts -map 0:d -c copy -f data klv_data.bin

# Decode extracted KLV (requires custom parser)
python decode_klv_file.py klv_data.bin
```

---

## Reference Decoder Implementation

Use the decoder from `tests/test_klv_receiver.py`:

```python
from tests.test_klv_receiver import decode_klv_packet

# Decode a KLV packet
klv_bytes = b'\x06\x0e\x2b\x34...'  # Your KLV data
telemetry = decode_klv_packet(klv_bytes)

if telemetry:
    print(f"Timestamp: {telemetry.get('timestamp_us')}")
    print(f"Lat/Lon: {telemetry.get('latitude')}, {telemetry.get('longitude')}")
    print(f"Altitude: {telemetry.get('altitude')} m")
    print(f"Roll: {telemetry.get('roll')}°")
    print(f"Pitch: {telemetry.get('pitch')}°")
    print(f"Heading: {telemetry.get('heading')}°")
```

---

## Common Issues

### Issue 1: "Invalid MISB 0601 key"
**Cause:** Packet doesn't start with the correct Universal Key  
**Solution:** Verify you're receiving the correct UDP port or MPEG-TS stream

### Issue 2: Missing GPS fields
**Cause:** Drone doesn't have GPS fix (indoors, no satellites)  
**Solution:** Only orientation data (roll, pitch, heading) will be present. This is normal.

### Issue 3: Struct unpack error
**Cause:** Corrupted packet or incorrect length  
**Solution:** Validate packet length matches BER-encoded length before parsing

### Issue 4: Can't extract from MPEG-TS
**Cause:** FFmpeg needs explicit data stream mapping  
**Solution:** Use `-map 0:d` to include data stream: `ffmpeg -i input.ts -map 0:d ...`

---

## MISB 0601 Resources

- **MISB Standard 0601**: Motion Imagery Standards Profile  
  https://gwg.nga.mil/misb/docs/standards/ST0601.16.pdf

- **KLV Overview**: Key-Length-Value encoding  
  https://en.wikipedia.org/wiki/KLV

- **BER Encoding**: Basic Encoding Rules  
  https://en.wikipedia.org/wiki/X.690#BER_encoding

---

## Summary

✅ **Encoder** (`klv_encoder.py`): Use on **ParrotForwarder** side  
✅ **Decoder** (`test_klv_receiver.py`): Use on **Receiver** side  
✅ **MISB 0601 Format**: Industry standard for UAS metadata  
✅ **Testing Tool**: `python tests/test_klv_receiver.py --port 12345`  
✅ **Stream Verification**: `ffprobe srt://host:8890`

For questions or issues, refer to the troubleshooting section in `README.md`.

