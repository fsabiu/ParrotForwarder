# ParrotForwarder

Captures H.264 video + MISB 0601 KLV telemetry from Parrot Anafi drones and
muxes them into a single MPEG-TS stream over SRT.

## Preferred deployment

Production should use `docker compose`, not an ad-hoc CLI session. The compose
stack:

- binds the dashboard on `0.0.0.0:8080`
- exposes the SRT stream on the machine's own network stack
- mounts `./config` and `./recordings`
- passes `/dev/bus/usb` through for the Skycontroller
- restarts the container after crashes and guest reboots via
  `restart: unless-stopped`

## Requirements

- Linux host or Linux VM guest with USB access to the controller
- Python 3.11
- Parrot Olympe SDK
- system GStreamer 1.x
- `protobuf==3.20.3`

## Run in Docker

```bash
docker compose up -d --build
curl http://127.0.0.1:8080/health
```

Dashboard address on the trusted LAN:

```text
http://<machine-ip>:8080/
```

Find the machine IP from inside the Linux host or guest:

```bash
hostname -I
ip -brief addr
```

If running in a VM, use bridged networking for the guest and enable USB
passthrough for the Skycontroller before starting the stack.

## Run under systemd

`parrot_forwarder.service` is a generic template. Adjust `User`, `Group`, and
`WorkingDirectory` for the target machine before enabling it.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now parrot_forwarder
sudo journalctl -u parrot_forwarder -f
```

## Architecture

```text
CLI (cli.py) -> ParrotForwarder coordinator (main.py)
                ├── TelemetryForwarder thread (telemetry.py)
                │     └── Parrot Olympe SDK -> KLV encoder (klv_encoder.py) -> UDP
                └── VideoForwarder thread (video.py)
                      └── GStreamer: RTSP in -> mux KLV -> MPEG-TS over SRT out
```

- `telemetry.py`: polls drone state, normalizes it, and encodes MISB 0601 KLV
- `video.py`: receives RTSP, muxes KLV, and publishes MPEG-TS over SRT
- `dashboard/`: operator UI for health, control, telemetry, preview, and recording
- `supervisor/`: FastAPI control plane, worker lifecycle, recording API, and dashboard

## Tests

```bash
make test
make lint
make typecheck
```
