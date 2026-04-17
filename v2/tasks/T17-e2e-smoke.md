# T17 - End-to-end smoke test

**Phase**: 4
**Depends on**: T16, T14

**Estimated effort**: M

## Goal

Drive the full pipeline end-to-end without a drone, using `videotestsrc` through the real GStreamer pipeline and an in-process SRT receiver.

## Acceptance criteria

- `tests/e2e/test_pipeline_smoke.py` starts the supervisor with the forwarder configured to use `videotestsrc` as the camera source (via env switch `PARROT_FORWARDER_E2E_FAKE_CAMERA=1`).
- Opens an SRT receiver on the output port; asserts >= 30 TS packets received within 10 s.
- Asserts KLV presence in the muxed stream (MISB 0601 sync bytes) at >= 1 Hz.
- Runs in CI on Ubuntu 24.04 runner with system gstreamer installed.

## Files touched

- `tests/e2e/` (new)
- `src/parrot_forwarder/forwarder/pipeline.py` (fake-camera switch)
