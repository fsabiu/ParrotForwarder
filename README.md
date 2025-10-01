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

- **Real-time telemetry streaming** at configurable rates (default: 10 Hz)
- **Video stream forwarding** with precise frame rate control (default: 30 fps)
- **USB connectivity** to Parrot Anafi drones via Skycontroller 3
- **Performance monitoring** with detailed FPS tracking and timing statistics
- **Modular architecture** with separate threaded forwarders for telemetry and video

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

ParrotForwarder uses a **multi-threaded architecture** to ensure independent, high-performance telemetry and video processing:

```
┌─────────────────────────────────────────────────────────────┐
│                    Parrot Anafi Drone                       │
│                  (via Skycontroller 3)                      │
└────────────────────┬────────────────────────────────────────┘
                     │ USB Connection (192.168.53.1)
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Raspberry Pi 4 - ParrotForwarder               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           Main Controller (ParrotForwarder)          │  │
│  │  - Drone connection management                       │  │
│  │  - Thread lifecycle control                          │  │
│  │  - Graceful shutdown handling                        │  │
│  └────┬──────────────────────────────────────────┬──────┘  │
│       │                                           │          │
│  ┌────▼─────────────────────┐   ┌───────────────▼──────┐  │
│  │  TelemetryForwarder      │   │   VideoForwarder     │  │
│  │  (Thread)                │   │   (Thread)           │  │
│  ├──────────────────────────┤   ├──────────────────────┤  │
│  │ • Reads drone state      │   │ • YUV frame callback │  │
│  │ • Collects telemetry     │   │ • YUV→BGR conversion │  │
│  │ • Precise 10 Hz timing   │   │ • Frame buffering    │  │
│  │ • JSON serialization     │   │ • Precise 30 fps     │  │
│  │ • Performance tracking   │   │ • Performance track  │  │
│  └────┬─────────────────────┘   └───────────┬──────────┘  │
│       │                                      │              │
│       │ [TODO: Output Implementation]       │              │
│       ▼                                      ▼              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Forwarding Layer (To Be Implemented)         │  │
│  │  • UDP/TCP streaming                                 │  │
│  │  • WebSocket connections                             │  │
│  │  • RTMP video encoding                               │  │
│  │  • Message queuing                                   │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │ VPN Connection
                          ▼
                   ┌──────────────┐
                   │ Remote Host  │
                   │  (Receiver)  │
                   └──────────────┘
```

### Key Design Principles

1. **Separation of Concerns**: Telemetry and video processing are completely independent
2. **Thread Safety**: All shared state protected with locks
3. **Precise Timing**: Target-time-based scheduling prevents drift accumulation
4. **Fail-Safe**: Each component handles errors independently without crashing others
5. **Observable**: Comprehensive performance metrics for production monitoring

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
  --drone-ip IP          Drone IP address (default: 192.168.53.1)
  --telemetry-fps FPS    Telemetry update rate in Hz (default: 10)
  --video-fps FPS        Video frame rate (default: 30)
  --duration SECONDS     Run duration in seconds (default: infinite)
  -h, --help            Show help message
```

### Example Configurations

#### Low Bandwidth (VPN-optimized)
```bash
python ParrotForwarder.py --telemetry-fps 5 --video-fps 15
```

#### High Performance (LAN)
```bash
python ParrotForwarder.py --telemetry-fps 20 --video-fps 30
```

#### Testing (30 second run)
```bash
python ParrotForwarder.py --duration 30
```

#### Custom Drone IP
```bash
python ParrotForwarder.py --drone-ip 192.168.42.1
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
├── ParrotForwarder.py          # Main application
├── test_drone_connection.py    # Telemetry testing script
├── test_video_stream.py        # Video stream testing script
├── requirements.txt            # Python dependencies
├── README.md                   # This file
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

- **`ParrotForwarder.py`**: Main application with `TelemetryForwarder` and `VideoForwarder` classes
- **`test_drone_connection.py`**: Standalone telemetry testing and verification
- **`test_video_stream.py`**: Standalone video streaming test with frame capture
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

