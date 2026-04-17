# T19 - Dockerfile and USB passthrough

**Phase**: 4
**Depends on**: T05

**Estimated effort**: M

## Goal

A container image that runs the supervisor with drone USB passthrough and exposes the dashboard port.

## Acceptance criteria

- `Dockerfile` (multi-stage), base `ubuntu:24.04`, target Python 3.11 via deadsnakes or pyenv.
- Installs all system deps (gstreamer, sdl2, etc.) and the package.
- `docker-compose.yml` example with:
  - USB device passthrough (`devices: - /dev/bus/usb`) documented.
  - Host-network mode documented as required for SRT out.
- `docs/runbook.md` has a "Running in Docker" section covering USB permissions, host networking, and the limitations (no hardware video accel inside container).
- Image size under 1.5 GB.

## Files touched

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `docs/runbook.md` (append)

## Notes

- Do not publish the image in v2. Users build locally.
