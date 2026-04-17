# T05 - install.sh and Makefile

**Phase**: 0
**Depends on**: T01
**Estimated effort**: S

## Goal

Single-command bootstrap of a fresh Ubuntu 24.04 ARM64 host to a running ParrotForwarder dev environment. Replaces the 6-block README install.

## Acceptance criteria

- `scripts/install.sh` is idempotent (safe to re-run). It:
  - Verifies Ubuntu 24.04 (warn if different, do not abort).
  - Installs apt deps: gstreamer stack, libsdl2, libjpeg, libopencv, build-essential.
  - Installs pyenv if not present (official installer, pinned commit).
  - Installs Python 3.11.10 via pyenv if not present.
  - Creates `.venv` at project root with pyenv 3.11.10.
  - Runs `pip install -e . -r requirements-dev.txt`.
  - Force-reinstalls `protobuf==3.20.3` (guard against Olympe's 3.7.1 transitive).
  - Verifies `gst-inspect-1.0 mpegtsmux` and `gst-inspect-1.0 srtsink` return non-zero exit codes.
  - Writes `/etc/parrot-forwarder/config.yaml` from the example if missing.
  - Prints a 3-line summary: venv path, config path, next-steps command.
- `Makefile` with targets: `install`, `test`, `lint`, `run`, `clean`. Each a one-liner calling the underlying tool.

## Files touched

- `scripts/install.sh`
- `Makefile`
- `README.md` install section collapses to `./scripts/install.sh`.

## How to verify

On a fresh VM (or VM snapshot pre-install):

```bash
./scripts/install.sh
source .venv/bin/activate
parrot-forwarder --help
make test
```

## Notes

- `set -euo pipefail` at top. Every apt-get includes `-y`.
- `sudo` only where needed (apt, writing to `/etc`). Not for pip.
- Emit one structured log line per step so re-runs are debuggable.
