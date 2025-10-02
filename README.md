# ParrotForwarder

**Real-time telemetry and video forwarding from Parrot Anafi drones**

A high-performance Python application for capturing and forwarding telemetry data and video streams from Parrot Anafi drones connected via USB to a Raspberry Pi 4. Designed for low-latency remote drone monitoring and control over VPN networks.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
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

ParrotForwarder is a professional-grade drone telemetry and video forwarding system built on Parrot's Olympe SDK. It provides:

- **Real-time telemetry streaming** at configurable rates (default: 10 Hz) via JSON over UDP
- **Video stream forwarding** with precise frame rate control (default: 30 fps)
- **USB connectivity** to Parrot Anafi drones via Skycontroller 3
- **Performance monitoring** with detailed FPS tracking and timing statistics
- **Modular architecture** with cleanly separated components and thread-safe operation
- **Connection retry logic** with graceful error handling and recovery

### Use Cases

- Remote drone monitoring over VPN
- Autonomous flight data collection
- Real-time video analytics
- Multi-receiver drone telemetry distribution
- Research and development with Parrot Anafi platforms

---

## Features

### ✅ Telemetry Forwarding

- **Comprehensive data collection:**
  - Battery level and state
  - GPS position (latitude, longitude, altitude)
  - Attitude (roll, pitch, yaw)
  - Speed (3D velocity vector)
  - Flying state
  - Altitude above ground level
- **Configurable update rate** (1-100 Hz)
- **JSON-formatted** telemetry with timestamps
- **Thread-safe** operation

### ✅ Video Forwarding

- **Live video stream** from Parrot Anafi camera
- **Automatic YUV to BGR conversion**
- **Configurable frame rate** (1-60 fps)
- **Thread-safe frame handling** with latest-frame buffering
- **Performance-optimized** for VPN transmission

### ✅ Performance Monitoring

- **Real-time FPS tracking** (target vs actual)
- **Loop timing statistics** (avg, min, max)
- **Performance indicators** (✓ ≥95%, ⚠ 80-95%, ✗ <80%)
- **Automatic warnings** for performance degradation
- **Detailed final statistics** on shutdown

### ✅ Production-Ready

- **Precise timing control** with drift compensation
- **Graceful error handling** and recovery
- **Comprehensive logging** with configurable levels
- **Clean shutdown** with Ctrl+C support
- **Modular design** for easy extension

---

## Architecture

ParrotForwarder uses a **modular, multi-threaded architecture** with clean separation of concerns for maintainability and extensibility:

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Parrot Anafi Drone                       │
│                  (via Skycontroller 3)                      │
└────────────────────┬────────────────────────────────────────┘
                     │ USB Connection (192.168.53.1)
                     │ - Olympe SDK Communication
                     │
┌────────────────────▼────────────────────────────────────────┐
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
│  │  • Graceful shutdown (KeyboardInterrupt)            │  │
│  │  • Resource cleanup                                  │  │
│  └────┬──────────────────────────────────────────┬──────┘  │
│       │                                           │          │
│  ┌────▼─────────────────────┐   ┌───────────────▼──────┐  │
│  │  TelemetryForwarder      │   │   VideoForwarder     │  │
│  │  (telemetry.py)          │   │   (video.py)         │  │
│  │  Thread 1                │   │   Thread 2           │  │
│  ├──────────────────────────┤   ├──────────────────────┤  │
│  │ • Reads drone state      │   │ • YUV frame callback │  │
│  │ • Collects telemetry     │   │ • YUV→BGR conversion │  │
│  │ • Precise 10 Hz timing   │   │ • Frame buffering    │  │
│  │ • JSON serialization     │   │ • Precise 30 fps     │  │
│  │ • UDP socket management  │   │ • Performance track  │  │
│  │ • Performance tracking   │   │ • [Video forwarding] │  │
│  └────┬─────────────────────┘   └───────────┬──────────┘  │
│       │ JSON over UDP                       │              │
│       │ (Non-blocking socket)               │              │
│       ▼                                      ▼              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Forwarding Layer                        │  │
│  │  Telemetry: ✓ JSON/UDP (Implemented)               │  │
│  │  Video:     ⏳ H.264/RTP (TODO)                     │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │ VPN Connection (Tailscale)
                          │ UDP Packets
                          ▼
                   ┌──────────────────────┐
                   │    Remote Host       │
                   │ telemetry_receiver.py│
                   │  - UDP listener      │
                   │  - JSON parser       │
                   │  - Telemetry display │
                   └──────────────────────┘
```

### Module Structure

The codebase is organized as a Python package with clear separation of concerns:

```
parrot_forwarder/
├── __init__.py          # Package exports (TelemetryForwarder, VideoForwarder, ParrotForwarder)
├── cli.py               # Command-line interface, argument parsing, logging setup
├── main.py              # ParrotForwarder coordinator class
├── telemetry.py         # TelemetryForwarder thread (independent telemetry handling)
└── video.py             # VideoForwarder thread (independent video handling)
```

**Benefits of Modular Design:**
- Each module has a single, well-defined responsibility
- Easy to test components in isolation
- Simple to extend (e.g., add new forwarding protocols)
- Clear dependency hierarchy (CLI → Main → Workers)
- Enables code reuse (import individual forwarders elsewhere)

### Thread Communication Model

```
Main Thread (ParrotForwarder)
    │
    ├─── Creates ──→ TelemetryForwarder Thread
    │                   │
    │                   ├─ Reads: Olympe drone.get_state()
    │                   ├─ Writes: UDP socket (non-blocking)
    │                   └─ Independent timing loop (10 Hz)
    │
    ├─── Creates ──→ VideoForwarder Thread
    │                   │
    │                   ├─ Receives: YUV callbacks (Olympe video thread)
    │                   ├─ Locks: self.lock for frame buffer
    │                   └─ Independent timing loop (30 fps)
    │
    └─── Monitors ──→ Graceful shutdown
                        - Calls stop() on both threads
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

**Telemetry Path:**
```
Drone State → get_state() → Telemetry Dict → JSON → UDP Socket → Remote Host
   (Olympe)     (10 Hz)      (Python)      (bytes)   (network)    (Receiver)
```

**Video Path (Current):**
```
Drone Camera → YUV Callback → BGR Conversion → Frame Buffer → [TODO: Encode → UDP/RTP]
   (H.264)      (Olympe)        (OpenCV)         (numpy)         (GStreamer)
```

### Performance Characteristics

| Component | Target | Typical Performance | Notes |
|-----------|--------|---------------------|-------|
| Telemetry Thread | 10 Hz | 10.01-10.04 Hz (100%+) | Consistently meets target |
| Video Thread | 30 fps | 28-30 fps (95-100%) | Limited by drone output |
| Loop Overhead | <1ms | 0.05-0.10ms avg | Minimal CPU usage |
| Connection Retry | Configurable | 5s default | Non-blocking for other operations |

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

- **Raspberry Pi 4** (2GB+ RAM recommended)
- **Parrot Anafi** drone with Skycontroller 3
- **USB connection** between Raspberry Pi and Skycontroller
- **Network connection** for VPN (WiFi or Ethernet)

### Software

- **Operating System**: Raspberry Pi OS (Debian-based)
- **Python**: 3.11.x (tested on 3.11.2)
- **Network**: USB interface at `192.168.53.1` (auto-configured by Skycontroller)

### Network Requirements

- Stable VPN connection for remote forwarding
- Recommended bandwidth: 3-10 Mbps (depends on video FPS and encoding)

---

## Installation

### 1. System Dependencies

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade

# Install required system packages
sudo apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    libsdl2-dev \
    libsdl2-2.0-0 \
    libjpeg-dev \
    libopencv-dev
```

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

# Run with default settings (telemetry: 10 Hz, video: 30 fps)
python ParrotForwarder.py
```

### Command-Line Options

```bash
python ParrotForwarder.py [OPTIONS]

Options:
  --drone-ip IP            Drone IP address (default: 192.168.53.1)
  --remote-host IP         Remote host IP to forward data to (required for forwarding)
  --telemetry-port PORT    UDP port for telemetry (default: 5000)
  --video-port PORT        UDP/RTP port for video (default: 5004)
  --telemetry-fps FPS      Telemetry update rate in Hz (default: 10)
  --video-fps FPS          Video frame rate (default: 30)
  --duration SECONDS       Run duration in seconds (default: infinite)
  --max-retries N          Maximum connection retry attempts (default: infinite)
  --retry-interval SECS    Seconds between connection retries (default: 5)
  --verbose                Enable verbose SDK logging
  -h, --help              Show help message
```

### Example Configurations

#### Remote Forwarding (VPN)
```bash
# Forward to remote host via VPN
python ParrotForwarder.py \
    --remote-host 100.103.235.98 \
    --telemetry-port 5000 \
    --video-port 5004
```

#### Low Bandwidth (VPN-optimized)
```bash
# Reduce rates for limited bandwidth
python ParrotForwarder.py \
    --remote-host 100.103.235.98 \
    --telemetry-fps 5 \
    --video-fps 15
```

#### High Performance (LAN)
```bash
# Higher rates for local network
python ParrotForwarder.py \
    --remote-host 192.168.1.100 \
    --telemetry-fps 20 \
    --video-fps 30
```

#### Testing (30 second run)
```bash
# Test run without forwarding
python ParrotForwarder.py --duration 30
```

#### Connection Retry Configuration
```bash
# Retry connection 5 times with 10 second intervals
python ParrotForwarder.py \
    --max-retries 5 \
    --retry-interval 10 \
    --remote-host 100.103.235.98
```

---

## Configuration

### Telemetry Data Fields

The telemetry forwarder collects the following data at each interval:

| Field | Type | Description | Units |
|-------|------|-------------|-------|
| `timestamp` | string | UTC timestamp (ISO 8601) | - |
| `sequence` | int | Sequential packet number | - |
| `battery_percent` | int | Battery level | % |
| `gps_fixed` | bool | GPS fix status | - |
| `latitude` | float | GPS latitude | degrees |
| `longitude` | float | GPS longitude | degrees |
| `altitude` | float | GPS altitude (MSL) | meters |
| `altitude_agl` | float | Altitude above ground | meters |
| `roll` | float | Roll angle | radians |
| `pitch` | float | Pitch angle | radians |
| `yaw` | float | Yaw angle | radians |
| `speed_x` | float | Velocity X (North) | m/s |
| `speed_y` | float | Velocity Y (East) | m/s |
| `speed_z` | float | Velocity Z (Down) | m/s |
| `flying_state` | string | Current flying state | enum |

### Performance Tuning

#### For VPN Transmission (Bandwidth-Limited)

```bash
# Reduce both rates
python ParrotForwarder.py --telemetry-fps 5 --video-fps 15
```

**Expected bandwidth**: 1-3 Mbps (with H.264 encoding)

#### For Local Development (Low Latency)

```bash
# Higher rates for responsive testing
python ParrotForwarder.py --telemetry-fps 20 --video-fps 30
```

**Expected bandwidth**: 3-8 Mbps (with H.264 encoding)

#### For Monitoring Only (Minimal Bandwidth)

```bash
# Very low rates for basic monitoring
python ParrotForwarder.py --telemetry-fps 2 --video-fps 5
```

**Expected bandwidth**: 0.5-1 Mbps

---

## Performance

### Typical Performance Metrics

On Raspberry Pi 4 (4GB), with default settings:

```
Telemetry Forwarder:
  ✓ Target: 10.0 fps, Actual: 10.01-10.04 fps (100.1-100.4%)
  Loop time: avg=0.10ms, min=0.07ms, max=0.50ms

Video Forwarder:
  ✓ Target: 30.0 fps, Forwarded: 28.5-29.8 fps (95-99%)
  Incoming: 30.0-30.2 fps from drone
  Loop time: avg=0.05ms, min=0.01ms, max=0.85ms
```

### Performance Indicators

- **✓ (Green)**: Performance ≥ 95% of target (optimal)
- **⚠ (Yellow)**: Performance 80-95% of target (acceptable)
- **✗ (Red)**: Performance < 80% of target (degraded)

### Monitoring Performance

Performance statistics are logged every 5 seconds:

```
[15:13:53] INFO - TelemetryForwarder - ✓ PERFORMANCE: 
    Target=10.0 fps, Actual=10.04 fps (100.4%) | 
    Loop: avg=0.10ms, min=0.07ms, max=0.27ms | 
    Count=253

[15:13:53] INFO - VideoForwarder - ✓ PERFORMANCE: 
    Target=30.0 fps, Forwarded=28.65 fps (95.5%) | 
    Incoming=30.2 fps, Received=719 | 
    Loop: avg=0.05ms, min=0.01ms, max=0.85ms
```

---

## Project Structure

```
drone/
├── ParrotForwarder.py          # Main entry point
├── parrot_forwarder/           # Main package (modular architecture)
│   ├── __init__.py             # Package initialization
│   ├── cli.py                  # Command-line interface
│   ├── main.py                 # ParrotForwarder coordinator
│   ├── telemetry.py            # TelemetryForwarder class
│   └── video.py                # VideoForwarder class
│
├── test_drone_connection.py    # Telemetry testing script
├── test_video_stream.py        # Video stream testing script
├── telemetry_receiver.py       # Test receiver for telemetry
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── LICENSE                     # MIT License
├── .gitignore                  # Git ignore patterns
│
├── drone_env/                  # Python virtual environment
│   ├── bin/
│   ├── lib/
│   └── ...
│
└── video_frames/               # Sample video frames (testing)
    ├── frame_001.jpg
    ├── frame_002.jpg
    └── ...
```

### Key Files

- **`ParrotForwarder.py`**: Main entry point script
- **`parrot_forwarder/`**: Modular package with separated concerns:
  - **`cli.py`**: Command-line argument parsing and main entry point
  - **`main.py`**: `ParrotForwarder` coordinator class managing connections and lifecycle
  - **`telemetry.py`**: `TelemetryForwarder` thread for telemetry data
  - **`video.py`**: `VideoForwarder` thread for video stream
- **`test_drone_connection.py`**: Standalone telemetry testing and verification
- **`test_video_stream.py`**: Standalone video streaming test with frame capture
- **`telemetry_receiver.py`**: Test receiver for verifying telemetry UDP forwarding
- **`requirements.txt`**: Pinned Python dependencies with versions

---

## Development

### Testing Scripts

#### Test Telemetry Connection

```bash
python test_drone_connection.py
```

Outputs comprehensive telemetry data including battery, GPS, altitude, attitude, speed, and flying state.

#### Test Video Stream

```bash
python test_video_stream.py
```

Captures and saves video frames to `video_frames/` directory for verification.

### Adding Forwarding Implementations

The placeholder methods `forward_telemetry()` and `forward_frame()` are ready for implementation:

#### Telemetry Forwarding (Example: UDP)

```python
def forward_telemetry(self, telemetry):
    """Forward telemetry via UDP."""
    import socket
    import json
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    message = json.dumps(telemetry).encode('utf-8')
    sock.sendto(message, (self.remote_host, self.remote_port))
```

#### Video Forwarding (Example: RTMP)

```python
def forward_frame(self, frame):
    """Forward frame via RTMP stream."""
    # Encode frame to H.264
    encoded = self.encoder.encode(frame)
    
    # Send to RTMP server
    self.rtmp_stream.write(encoded)
    
    self.forwarded_count += 1
```

### Logging Levels

Adjust logging verbosity:

```python
# In ParrotForwarder.py, modify:
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG, INFO, WARNING, ERROR
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
    datefmt='%H:%M:%S'
)
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

### Video Stream Errors

**Problem**: `No frames received from stream`

**Solutions**:
1. Ensure drone camera is active (not in standby)
2. Check for H.264 decoder warnings in logs
3. Verify video stream is enabled on drone
4. Try restarting the drone and Skycontroller

### Performance Degradation

**Problem**: `Video forwarding is running at 85% of target FPS`

**Solutions**:
1. Reduce target FPS: `--video-fps 20`
2. Check CPU usage: `top` or `htop`
3. Ensure no other heavy processes are running
4. Consider using hardware encoding for video

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
- **Raspberry Pi Foundation** for the excellent hardware platform
- **OpenCV Community** for video processing capabilities

---

## Contact

For questions, issues, or contributions, please open an issue on GitHub.

---

**Built with ❤️ for autonomous drone applications**

