# ParrotForwarder

**Unified video and telemetry streaming from Parrot Anafi drones with synchronized KLV metadata**

A professional-grade drone streaming system that unifies H.264 video and MISB 0601 KLV telemetry into a single MPEG-TS stream over SRT. Built on Parrot's Olympe SDK and GStreamer, designed for low-latency UAS operations over VPN networks.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![GStreamer 1.14+](https://img.shields.io/badge/GStreamer-1.14+-green.svg)](https://gstreamer.freedesktop.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Performance](#performance)
- [Project Structure](#project-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

ParrotForwarder is a professional-grade UAS streaming system that synchronizes video and telemetry into a unified transport stream. It provides:

- **Synchronized video + telemetry** in single MPEG-TS stream with inherent timestamp alignment
- **MISB 0601 KLV metadata** encoding for standard-compliant telemetry
- **H.264 video @ 1280x720, 29.97fps** with no re-encoding (low latency)
- **SRT streaming** for reliable, low-latency delivery over unreliable networks
- **USB connectivity** to Parrot Anafi drones via Skycontroller 3
- **GStreamer-based muxing** for professional-grade stream composition
- **Modular architecture** with cleanly separated components and thread-safe operation

### Use Cases

- UAS operations requiring synchronized video and telemetry
- Remote drone monitoring over VPN with MISB-compliant metadata
- Real-time video analytics with embedded position and attitude data
- Professional drone recording with standard KLV metadata
- Research and development with Parrot Anafi platforms

---

## Features

### ✅ Unified Stream Architecture

- **Single MPEG-TS stream** containing both video and telemetry data
- **Inherent synchronization** - video and telemetry timestamps aligned in same transport stream
- **MISB 0601 KLV metadata** encoding for telemetry (industry standard)
- **SRT output** for reliable streaming over unreliable networks
- **No re-encoding** - video copied directly for minimal latency

### ✅ Video Stream

- **H.264 video @ 1280x720, 29.97fps** from Parrot Anafi camera
- **Copy mode** (no transcoding) for lowest possible latency
- **RTSP input** from drone, converted to MPEG-TS
- **Byte-stream format** with proper AU alignment
- **GStreamer pipeline** for professional-grade processing

### ✅ Telemetry/KLV Metadata

- **MISB 0601 compliant** KLV encoding
- **10 Hz update rate** for telemetry
- **Comprehensive data:**
  - Unix timestamp (microseconds)
  - GPS position (latitude, longitude, altitude MSL)
  - Attitude (roll, pitch, yaw in radians)
  - Battery level
  - GPS fix status
- **Validation and scaling** per MISB 0601 specification
- **UDP transport** for local KLV→GStreamer communication

### ✅ Performance Monitoring

- **Real-time FPS tracking** (target vs actual)
- **Telemetry performance:** 10.0 fps actual, 0 errors
- **Video performance:** 29.97 fps from drone
- **Loop timing statistics** (avg, min, max)
- **Performance indicators** (✓ ≥95%, ⚠ 80-95%, ✗ <80%)
- **Detailed final statistics** on shutdown

### ✅ Production-Ready

- **systemd service integration** for automatic startup
- **Dynamic port allocation** for KLV stream
- **Graceful error handling** and recovery
- **Comprehensive logging** with configurable levels
- **Clean shutdown** with proper resource cleanup
- **Modular design** with separation of concerns

---

## Architecture

ParrotForwarder uses a **unified streaming architecture** that synchronizes video and telemetry into a single MPEG-TS stream with KLV metadata:

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Parrot Anafi Drone                       │
│                  (via Skycontroller 3)                      │
└─────────────┬──────────────────────────┬────────────────────┘
              │ USB (192.168.53.1)       │
              │ RTSP Video               │ Telemetry via Olympe
              │ H.264 @ 1280x720         │ (Attitude, GPS, Battery)
              │                          │
┌─────────────▼──────────────────────────▼────────────────────┐
│              Raspberry Pi 4 - ParrotForwarder               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              CLI Layer (cli.py)                      │  │
│  │  - Argument parsing                                  │  │
│  │  - Logging configuration                             │  │
│  │  - Application entry point                           │  │
│  └────┬─────────────────────────────────────────────────┘  │
│       │                                                     │
│  ┌────▼─────────────────────────────────────────────────┐  │
│  │        Main Controller (main.py)                     │  │
│  │        ParrotForwarder Class                         │  │
│  ├──────────────────────────────────────────────────────┤  │
│  │  • Drone connection with retry logic                │  │
│  │  • Thread lifecycle management                       │  │
│  │  • Dynamic KLV port allocation                       │  │
│  │  • Graceful shutdown (KeyboardInterrupt)            │  │
│  └────┬──────────────────────────────────────────┬──────┘  │
│       │                                           │          │
│  ┌────▼─────────────────────┐   ┌───────────────▼──────┐  │
│  │  TelemetryForwarder      │   │   VideoForwarder     │  │
│  │  (telemetry.py)          │   │   (video.py)         │  │
│  │  Thread 1                │   │   Thread 2           │  │
│  ├──────────────────────────┤   ├──────────────────────┤  │
│  │ • Reads drone state      │   │ • GStreamer pipeline │  │
│  │ • Collects telemetry     │   │ • RTSP input (drone) │  │
│  │ • Encodes to KLV         │   │ • UDP input (KLV)    │  │
│  │ • MISB 0601 format       │   │ • mpegtsmux          │  │
│  │ • Precise 10 Hz timing   │   │ • SRT output         │  │
│  │ • Sends to localhost UDP │   │ • 0:Video + 1:Data   │  │
│  └────┬─────────────────────┘   └───────────┬──────────┘  │
│       │ KLV over UDP (localhost:12345)      │              │
│       │                                      │              │
│       └──────────────────┬───────────────────┘              │
│                          │                                  │
│  ┌───────────────────────▼──────────────────────────────┐  │
│  │          GStreamer Muxing Pipeline                   │  │
│  │                                                       │  │
│  │  rtspsrc → rtph264depay → h264parse ─┐              │  │
│  │                                       ├─→ mpegtsmux  │  │
│  │  udpsrc → meta/x-klv ────────────────┘      │        │  │
│  │                                              ↓        │  │
│  │                                           srtsink     │  │
│  │                                         (port 8890)   │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │ VPN/Network
                          │ Single SRT Stream (MPEG-TS)
                          │ Stream 0: Video (H.264)
                          │ Stream 1: Data (KLV)
                          ▼
                   ┌──────────────────────┐
                   │    Remote Client     │
                   │  (ffplay/VLC/custom) │
                   │  srt://host:8890     │
                   │  - Synchronized A/V  │
                   │  - Embedded metadata │
                   └──────────────────────┘
```

### Module Structure

The codebase is organized as a Python package with clear separation of concerns:

```
parrot_forwarder/
├── __init__.py          # Package exports
├── cli.py               # Command-line interface, argument parsing, logging setup
├── main.py              # ParrotForwarder coordinator class
├── telemetry.py         # TelemetryForwarder thread (drone→KLV encoding)
├── video.py             # VideoForwarder thread (GStreamer muxing pipeline)
└── klv_encoder.py       # MISB 0601 KLV encoder implementation
```

**Benefits of Modular Design:**
- Each module has a single, well-defined responsibility
- Custom KLV encoder with MISB 0601 compliance
- Easy to test components in isolation (e.g., test_klv_receiver.py)
- Clear dependency hierarchy (CLI → Main → Workers → Encoder)
- GStreamer integration for professional-grade muxing
- Enables code reuse (import individual forwarders elsewhere)

### Thread Communication Model

```
Main Thread (ParrotForwarder)
    │
    ├─── Creates ──→ TelemetryForwarder Thread
    │                   │
    │                   ├─ Reads: Olympe drone.get_state()
    │                   ├─ Encodes: JSON → KLV (MISB 0601)
    │                   ├─ Writes: UDP socket to localhost:12345
    │                   └─ Independent timing loop (10 Hz)
    │
    ├─── Creates ──→ VideoForwarder Thread
    │                   │
    │                   ├─ Spawns: GStreamer subprocess
    │                   ├─ Input 1: RTSP from drone (video)
    │                   ├─ Input 2: UDP from localhost (KLV)
    │                   ├─ Mux: mpegtsmux (video+data)
    │                   └─ Output: SRT stream on port 8890
    │
    └─── Monitors ──→ Graceful shutdown
                        - Calls stop() on both threads
                        - Terminates GStreamer (SIGINT)
                        - Waits for threads to finish (join)
                        - Closes drone connection
```

### Key Design Principles

1. **Separation of Concerns**: Each module handles one aspect of the system
   - CLI handles user interface
   - Main handles coordination
   - Workers handle specific data streams

2. **Thread Independence**: Telemetry and video processing run completely independently
   - No shared state between forwarders
   - Independent performance characteristics
   - Isolated error handling

3. **Thread Safety**: Shared resources protected with locks
   - `threading.Lock` for video frame buffer
   - Non-blocking UDP sockets prevent blocking

4. **Precise Timing**: Target-time-based scheduling prevents drift
   - `next_frame_time += interval` (not `sleep(interval)`)
   - Automatic drift detection and reset
   - Performance warnings if falling behind

5. **Fail-Safe Operation**: Graceful error handling at every level
   - Connection retry logic with exponential backoff
   - Per-thread exception handling
   - Clean shutdown on `KeyboardInterrupt`
   - Resource cleanup in finally blocks

6. **Observable Performance**: Real-time metrics for production monitoring
   - Actual vs target FPS tracking
   - Loop timing statistics (avg, min, max)
   - Performance indicators (✓ ⚠ ✗)
   - UDP send statistics (packets sent, errors)

7. **Extensibility**: Easy to add new features
   - Add new forwarders (e.g., audio, metadata)
   - Swap forwarding protocols (UDP → TCP → WebSocket)
   - Add data transformations (filters, compression)
   - Implement recording capabilities

### Data Flow

**Unified Stream Path:**
```
┌─ Telemetry ─────────────────────────────────────┐
│ Drone State → get_state() → KLV Encoder →       │
│  (Olympe)      (10 Hz)       (MISB 0601)        │
│                                   ↓              │
│                              UDP localhost:12345 │
└──────────────────────────────────┼──────────────┘
                                   │
                                   ↓
                          ┌─── GStreamer ───┐
                          │   mpegtsmux     │
                          │  (synchronize)  │
                          └────────┬────────┘
                                   ↑
┌─ Video ────────────────────────┼────────────────┐
│ Drone Camera → RTSP Stream → rtph264depay →     │
│   (H.264)    (192.168.53.1)   h264parse         │
│               1280x720@30                        │
└──────────────────────────────────────────────────┘
                                   │
                                   ↓
                          ┌─── MPEG-TS ────┐
                          │ Stream 0: Video │
                          │ Stream 1: Data  │
                          └────────┬────────┘
                                   │
                                   ↓
                            SRT Output
                        (port 8890, listener)
                                   │
                                   ↓
                          Remote Client(s)
```

### Performance Characteristics

| Component | Target | Typical Performance | Notes |
|-----------|--------|---------------------|-------|
| Telemetry Thread | 10 Hz | 10.0 Hz (100%) | KLV encoding @ 10 fps, 0 errors |
| Video Stream | 29.97 fps | 29.97 fps | H.264 from drone, no transcoding |
| Unified Stream | N/A | Video + Data | Both streams synchronized in MPEG-TS |
| KLV Encoding | <1ms | ~0.1ms per packet | MISB 0601 encoding overhead |
| GStreamer Latency | 200ms | Configurable | Set in pipeline parameters |
| SRT Latency | 200ms | Configurable | Set in srtsink parameters |
| Total End-to-End | ~400ms | Video + KLV synchronized | Suitable for monitoring applications |

### Error Handling Strategy

```
Level 1: Method-level
  └─ Try/catch in individual methods (e.g., forward_telemetry)
     └─ Log error, increment error counter, continue

Level 2: Loop-level
  └─ Try/catch in thread run() loops
     └─ Log error, reset timing, continue loop

Level 3: Thread-level
  └─ Catch KeyboardInterrupt in run() methods
     └─ Set running=False, exit gracefully

Level 4: Application-level
  └─ Catch KeyboardInterrupt in main()
     └─ Stop all threads, disconnect, exit cleanly
```

This layered approach ensures that errors at any level are handled appropriately without crashing the entire system.

---

## System Requirements

### Hardware

- **Raspberry Pi 4** (2GB+ RAM recommended, 4GB preferred)
- **Parrot Anafi** drone with Skycontroller 3
- **USB connection** between Raspberry Pi and Skycontroller
- **Network connection** for VPN (WiFi or Ethernet)

### Software

- **Operating System**: Raspberry Pi OS (Debian-based) or Ubuntu
- **Python**: 3.11.x (tested on 3.11.2)
- **GStreamer**: 1.14+ (system installation via apt, not Anaconda)
  - Core: `gstreamer1.0-tools`, `gstreamer1.0-plugins-base`
  - Plugins: `gstreamer1.0-plugins-good`, `gstreamer1.0-plugins-bad`
  - Required: `mpegtsmux`, `srtsink`, `rtspsrc` elements
- **Network**: USB interface at `192.168.53.1` (auto-configured by Skycontroller)

### Network Requirements

- Stable VPN connection for remote streaming (Tailscale recommended)
- Recommended bandwidth: 2-5 Mbps for unified stream
  - Video: H.264 @ 1280x720, ~2-4 Mbps
  - KLV metadata: ~10 packets/sec, minimal bandwidth (<1 Kbps)
- SRT provides error correction over unreliable networks

---

## Installation

### 1. System Dependencies

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade

# Install Python and basic dependencies
sudo apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    libsdl2-dev \
    libsdl2-2.0-0 \
    libjpeg-dev \
    libopencv-dev

# Install GStreamer
sudo apt-get install -y \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-rtsp

# Verify GStreamer installation
gst-inspect-1.0 mpegtsmux  # Should show mpegtsmux element
gst-inspect-1.0 srtsink    # Should show srtsink element
```

**Important**: Make sure you're using the system GStreamer (`/usr/bin/gst-launch-1.0`), not an Anaconda/Conda version which may be outdated.

### 2. Clone Repository

```bash
git clone <repository-url> drone
cd drone
```

### 3. Create Virtual Environment

```bash
# Create virtual environment with Python 3.11
python3.11 -m venv drone_env

# Activate environment
source drone_env/bin/activate
```

### 4. Install Python Dependencies

```bash
# Install all required packages
pip install -r requirements.txt
```

**Important**: The `requirements.txt` includes `protobuf==3.20.3` which is critical for compatibility with Python 3.11+. Do not upgrade protobuf to 4.x.

### 5. Verify Installation

```bash
# Test drone connection (with drone powered on and connected)
python test_drone_connection.py

# Test video stream
python test_video_stream.py
```

---

## Usage

### Basic Usage

```bash
# Activate virtual environment
source drone_env/bin/activate

# Run with default settings (SRT output on port 8890)
python ParrotForwarder.py
```

The unified stream will be available at `srt://<raspberry-pi-ip>:8890`

### Command-Line Options

```bash
python ParrotForwarder.py [OPTIONS]

Options:
  --drone-ip IP            Drone IP address (default: 192.168.53.1)
  --srt-port PORT          SRT output port (default: 8890)
  --telemetry-fps FPS      Telemetry/KLV update rate in Hz (default: 10)
  --duration SECONDS       Run duration in seconds (default: infinite)
  --max-retries N          Maximum connection retry attempts (default: infinite)
  --retry-interval SECS    Seconds between connection retries (default: 5)
  --verbose                Enable verbose SDK logging
  -h, --help               Show help message
```

### Viewing the Stream

#### Using ffplay (FFmpeg)
```bash
# Basic playback with low latency
ffplay -fflags nobuffer -flags low_delay srt://<raspberry-pi-ip>:8890

# View video only
ffplay -fflags nobuffer -flags low_delay srt://100.105.188.84:8890

# View stream info (shows both video and KLV data streams)
ffprobe srt://100.105.188.84:8890
```

#### Recording the Stream
```bash
# Record 10 seconds of unified stream (video + KLV)
ffmpeg -i srt://100.105.188.84:8890 -c copy -map 0:v -map 0:d -t 10 recording.ts

# Extract KLV metadata from recorded file
ffmpeg -i recording.ts -map 0:d -c copy -f data klv_data.bin
```

### Example Configurations

#### Standard Operation (Production)
```bash
# Run as systemd service (automatic startup)
sudo systemctl start parrot_forwarder
sudo journalctl -u parrot_forwarder -f  # View logs
```

#### Custom SRT Port
```bash
# Use different SRT port
python ParrotForwarder.py --srt-port 9000
```

#### Testing (30 second run)
```bash
# Test run with automatic shutdown
python ParrotForwarder.py --duration 30
```

#### Connection Retry Configuration
```bash
# Retry connection 5 times with 10 second intervals
python ParrotForwarder.py \
    --max-retries 5 \
    --retry-interval 10
```

---

## Configuration

### KLV Telemetry Data Fields

The telemetry forwarder encodes the following MISB 0601 KLV tags at 10 Hz:

| MISB 0601 Tag | Field | Type | Description | Encoding |
|---------------|-------|------|-------------|----------|
| Tag 2 | `timestamp` | uint64 | Unix timestamp | Microseconds since epoch |
| Tag 13 | `latitude` | int32 | Sensor latitude | Degrees × 10^7, range ±90° |
| Tag 14 | `longitude` | int32 | Sensor longitude | Degrees × 10^7, range ±180° |
| Tag 15 | `altitude` | uint16 | Sensor altitude MSL | Meters, 0-19,900m range |
| Tag 5 | `roll` | int16 | Platform roll | Degrees × 100, range ±180° |
| Tag 6 | `pitch` | int16 | Platform pitch | Degrees × 100, range ±90° |
| Tag 7 | `yaw` | uint16 | Platform heading | Degrees × 100, 0-360° |

**Additional drone data collected (not in KLV stream):**
- Battery level (%)
- GPS fix status
- Flying state
- Altitude AGL
- Speed vector (x, y, z)

**KLV Packet Structure:**
- Universal Label: `06 0E 2B 34 02 0B 01 01 0E 01 03 01 01 00 00 00`
- Length: Variable (BER encoding)
- Data: TLV-encoded fields per MISB 0601

### Performance Tuning

#### GStreamer Latency Configuration

The default latency is 200ms for both RTSP input and SRT output. To adjust:

Edit `parrot_forwarder/video.py` and modify the pipeline:
```python
# Reduce latency (may cause stuttering on poor networks)
"rtspsrc ... latency=100 ! ... srtsink ... latency=100"

# Increase latency (smoother playback on poor networks)
"rtspsrc ... latency=500 ! ... srtsink ... latency=500"
```

#### KLV Update Rate

```bash
# Lower rate for bandwidth-constrained networks
python ParrotForwarder.py --telemetry-fps 5

# Higher rate for more frequent telemetry updates
python ParrotForwarder.py --telemetry-fps 20
```

**Note**: Video rate (29.97 fps) is fixed by the drone and cannot be changed.

#### Expected Bandwidth

| Configuration | Video | KLV | Total | Use Case |
|---------------|-------|-----|-------|----------|
| Standard | 2-4 Mbps | <1 Kbps | 2-4 Mbps | Normal operations |
| Over VPN | 2-4 Mbps | <1 Kbps | 2-4 Mbps | Tailscale/WireGuard |
| Poor network | 2-4 Mbps | <1 Kbps | 2-4 Mbps | SRT handles packet loss |

SRT protocol provides Forward Error Correction and automatic retransmission, making it suitable for unreliable networks.

---

## Performance

### Typical Performance Metrics

On Raspberry Pi 4 (4GB), with default settings:

```
Telemetry Forwarder:
  ✓ Target: 10.0 fps, Actual: 10.0 fps (100.0%)
  KLV packets sent: 600 (10/sec)
  Errors: 0
  Loop time: avg=0.08ms, min=0.05ms, max=0.15ms

Video Forwarder (GStreamer):
  ✓ Input: RTSP from drone @ 29.97 fps
  ✓ Output: MPEG-TS over SRT @ 29.97 fps
  ✓ KLV muxed: 10 packets/sec
  Status: Running, no errors

Unified Stream:
  ✓ Stream 0: Video (H.264) - 1280x720 @ 29.97 fps
  ✓ Stream 1: Data (KLV) - MISB 0601 @ 10 Hz
  ✓ Synchronization: Inherent via MPEG-TS timestamps
```

### Performance Indicators

- **✓ (Green)**: Performance ≥ 95% of target (optimal)
- **⚠ (Yellow)**: Performance 80-95% of target (acceptable)
- **✗ (Red)**: Performance < 80% of target (degraded)

### Monitoring Performance

Performance statistics are logged every 5 seconds:

```
[21:32:05] INFO - TelemetryForwarder - ✓ PERFORMANCE: 
    Target=10.0 fps, Actual=10.0 fps (100.0%) | 
    Loop: avg=0.08ms, min=0.05ms, max=0.15ms | 
    KLV packets sent: 50, Errors: 0

[21:32:05] INFO - VideoForwarder - ✓ GStreamer pipeline running
    Input: rtsp://192.168.53.1/live
    Output: srt://0.0.0.0:8890 (MPEG-TS with KLV)

# View logs in real-time
sudo journalctl -u parrot_forwarder -f
```

---

## Project Structure

```
ParrotForwarder/
├── ParrotForwarder.py              # Main entry point
├── parrot_forwarder/               # Main package (modular architecture)
│   ├── __init__.py                 # Package initialization
│   ├── cli.py                      # Command-line interface
│   ├── main.py                     # ParrotForwarder coordinator
│   ├── telemetry.py                # TelemetryForwarder (JSON→KLV encoding)
│   ├── video.py                    # VideoForwarder (GStreamer pipeline)
│   └── klv_encoder.py              # MISB 0601 KLV encoder
│
├── tests/                          # Testing utilities
│   ├── test_drone_connection.py    # Telemetry testing script
│   ├── test_video_stream.py        # Video stream testing script
│   └── test_klv_receiver.py        # KLV packet decoder/viewer
│
├── parrot_forwarder.service        # systemd service file
├── requirements.txt                # Python dependencies
├── GSTREAMER_SETUP.md             # GStreamer installation guide
├── README.md                       # This file
├── LICENSE                         # MIT License
└── .gitignore                      # Git ignore patterns
```

### Key Files

- **`ParrotForwarder.py`**: Main entry point script
- **`parrot_forwarder/`**: Modular package with separated concerns:
  - **`cli.py`**: Command-line argument parsing and main entry point
  - **`main.py`**: `ParrotForwarder` coordinator class managing connections and lifecycle
  - **`telemetry.py`**: `TelemetryForwarder` thread for KLV encoding and UDP transmission
  - **`video.py`**: `VideoForwarder` thread managing GStreamer muxing pipeline
  - **`klv_encoder.py`**: Custom MISB 0601 KLV encoder with validation
- **`tests/test_klv_receiver.py`**: Python script to receive and decode KLV packets
- **`parrot_forwarder.service`**: systemd service for automatic startup
- **`GSTREAMER_SETUP.md`**: GStreamer installation and troubleshooting guide
- **`requirements.txt`**: Pinned Python dependencies with versions

---

## Development

### Testing Scripts

#### Test KLV Receiver

```bash
# Listen for KLV packets and decode them
python tests/test_klv_receiver.py --port 12345

# Output shows decoded telemetry in real-time:
# Timestamp: 2025-10-06 21:32:05.123456
# Latitude: 37.7749, Longitude: -122.4194
# Altitude: 125.5m MSL
# Roll: -5.2°, Pitch: 2.1°, Yaw: 180.0°
```

#### Test Telemetry Connection

```bash
python tests/test_drone_connection.py
```

Outputs comprehensive telemetry data including battery, GPS, altitude, attitude, speed, and flying state.

#### Test Video Stream

```bash
python tests/test_video_stream.py
```

Captures and saves video frames for verification.

### Testing the Unified Stream

```bash
# 1. Start ParrotForwarder
python ParrotForwarder.py

# 2. In another terminal, view stream info
ffprobe srt://localhost:8890

# Expected output:
#   Stream #0:0: Video: h264, 1280x720, 29.97 fps
#   Stream #0:1: Data: klv (KLVA / 0x41564C4B)

# 3. Record 10 seconds with both streams
ffmpeg -i srt://localhost:8890 -c copy -map 0:v -map 0:d -t 10 test.ts

# 4. Verify recording
ffprobe test.ts
```

### Modifying KLV Encoding

To add new MISB 0601 tags, edit `parrot_forwarder/klv_encoder.py`:

```python
class MISB0601Encoder:
    def add_custom_field(self, tag_number, value):
        """Add a custom MISB 0601 tag."""
        # Encode value according to MISB 0601 spec
        encoded = self._encode_value(value)
        self.fields[tag_number] = encoded
```

### Logging Levels

Adjust logging verbosity by modifying the systemd service or command line:

```bash
# For systemd service, edit parrot_forwarder.service:
ExecStart=/path/to/python ParrotForwarder.py --verbose

# Or run directly with DEBUG logging:
python ParrotForwarder.py --verbose
```

---

## Troubleshooting

### Drone Connection Issues

**Problem**: `Failed to connect to drone at 192.168.53.1`

**Solutions**:
1. Verify USB connection between Raspberry Pi and Skycontroller
2. Check network interface: `ip addr show usb0`
3. Ensure Skycontroller is powered on and drone is connected
4. Verify IP address: `ping 192.168.53.1`

### GStreamer Issues

**Problem**: `No such element or plugin 'mpegtsmux'`

**Solutions**:
1. Install missing plugins: `sudo apt-get install gstreamer1.0-plugins-bad`
2. Verify installation: `gst-inspect-1.0 mpegtsmux`
3. Check GStreamer version: `gst-launch-1.0 --version` (need 1.14+)
4. Ensure using system GStreamer, not Anaconda: `which gst-launch-1.0` should show `/usr/bin/`

**Problem**: `No such element or plugin 'srtsink'`

**Solutions**:
1. Install SRT support: `sudo apt-get install gstreamer1.0-plugins-bad`
2. If still missing, SRT plugin may not be compiled in your GStreamer build
3. Alternative: Use `udpsink` and run FFmpeg separately for SRT output

**Problem**: `GStreamer pipeline terminated unexpectedly`

**Solutions**:
1. Check logs: `sudo journalctl -u parrot_forwarder -n 100`
2. Test RTSP manually: `gst-launch-1.0 rtspsrc location=rtsp://192.168.53.1/live ! fakesink`
3. Verify KLV port is sending data: `python tests/test_klv_receiver.py --port 12345`
4. Enable GStreamer debug: `GST_DEBUG=3 python ParrotForwarder.py`

### SRT Connection Issues

**Problem**: Client can't connect to SRT stream

**Solutions**:
1. Check firewall: `sudo ufw allow 8890`
2. Verify stream is running: `sudo netstat -tlnp | grep 8890`
3. Test locally first: `ffplay srt://localhost:8890`
4. Ensure VPN/network allows SRT port
5. Check SRT URL format: `srt://host:port` (no query string needed for client connections)

### KLV/Telemetry Issues

**Problem**: `Stream #0:1: Data: klv` appears in ffprobe but no telemetry

**Solutions**:
1. Check TelemetryForwarder is running and sending packets
2. Verify KLV port: `python tests/test_klv_receiver.py --port 12345`
3. Check for GPS fix - drone may be sending placeholder coordinates indoors
4. Review logs for KLV encoding errors: `sudo journalctl -u parrot_forwarder | grep KLV`

**Problem**: `struct.error: 'i' format requires ...` in KLV encoder

**Solutions**:
1. This occurs when GPS is not fixed (invalid coordinates)
2. The encoder automatically validates coordinates and skips invalid values
3. Fly drone outdoors or wait for GPS fix
4. Check logs for "GPS not fixed" messages

### Performance Degradation

**Problem**: High CPU usage or stuttering video

**Solutions**:
1. Check CPU usage: `top` or `htop`
2. Ensure no other heavy processes are running
3. Increase GStreamer buffer: Edit pipeline `latency=500`
4. Reduce KLV rate: `--telemetry-fps 5`
5. Check network bandwidth with `iftop` or similar

### Import Errors

**Problem**: `ModuleNotFoundError: No module named 'olympe'`

**Solutions**:
1. Activate virtual environment: `source drone_env/bin/activate`
2. Reinstall dependencies: `pip install -r requirements.txt`
3. Verify Python version: `python --version` (should be 3.11.x)

### Protobuf Compatibility

**Problem**: `AttributeError: module 'collections' has no attribute 'MutableMapping'`

**Solutions**:
1. Ensure protobuf < 4.0: `pip install "protobuf==3.20.3"`
2. Use Python 3.11 (not 3.12+)
3. Recreate virtual environment if needed

---

## Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/amazing-feature`
3. **Commit** your changes: `git commit -m 'Add amazing feature'`
4. **Push** to the branch: `git push origin feature/amazing-feature`
5. **Open** a Pull Request

### Code Style

- Follow PEP 8 guidelines
- Use type hints where appropriate
- Add docstrings to all classes and methods
- Maintain modularity and separation of concerns

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- **Parrot Developers** for the [Olympe SDK](https://developer.parrot.com/docs/olympe/)
- **GStreamer Community** for the powerful multimedia framework
- **SRT Alliance** for the Secure Reliable Transport protocol
- **MISB** for the KLV metadata standards (Motion Imagery Standards Board)
- **Raspberry Pi Foundation** for the excellent hardware platform
- **OpenCV Community** for video processing capabilities

---

## Contact

For questions, issues, or contributions, please open an issue on GitHub.

---

**Built with ❤️ for autonomous drone applications**

