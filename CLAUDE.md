# ParrotForwarder

Captures H.264 video + MISB 0601 KLV telemetry from Parrot Anafi drones and muxes them into a single MPEG-TS stream over SRT.

## Environment & Installation

- Requires **Python 3.11+** and **Parrot Olympe SDK**
- **Critical**: `protobuf==3.20.3` must stay below 4.0 for Python 3.11+ compatibility
- Requires **system GStreamer 1.14+** (not the Anaconda/Conda version - mixing Conda and system GStreamer causes crashes)
- Install: `pip install -r requirements.txt` in the Parrot Olympe conda environment

## Running

```bash
# Basic usage
python ParrotForwarder.py --drone-ip 192.168.42.1 --srt-port 8888

# With auto-reconnect and custom telemetry rate
python ParrotForwarder.py --drone-ip 192.168.42.1 --srt-port 8888 --auto-reconnect --telemetry-fps 10

# Run as systemd service (deployed on oracle user)
sudo systemctl start parrot-forwarder
sudo journalctl -u parrot-forwarder -f
```

## Architecture

```
CLI (cli.py) -> ParrotForwarder coordinator (main.py)
                ├── TelemetryForwarder thread (telemetry.py)
                │     └── Parrot Olympe SDK -> KLV encoder (klv_encoder.py) -> UDP
                └── VideoForwarder thread (video.py)
                      └── GStreamer: RTSP in -> mux KLV -> MPEG-TS over SRT out
```

- **TelemetryForwarder**: polls drone state at 10 Hz, encodes to MISB 0601 KLV, sends via UDP
- **VideoForwarder**: GStreamer pipeline receives RTSP from drone, muxes KLV, outputs SRT
- **klv_encoder.py**: Custom MISB 0601 KLV encoder (13+ fields: GPS, attitude, gimbal, camera params, timestamps)
- **Deployment**: systemd service, `oracle` user at `/home/oracle/ParrotForwarder/`, Anaconda `parrot` env

## Tests

```bash
cd tests
python test_drone_connection.py --drone-ip 192.168.42.1
python test_klv_receiver.py      # Receive and decode KLV packets
python test_video_stream.py      # Verify video output
```
