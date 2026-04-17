# T14 - Video preview (HLS or WebRTC)

**Phase**: 3
**Depends on**: T13
**Estimated effort**: L

## Goal

Live video preview in the dashboard. Main SRT stream must remain untouched.

## Acceptance criteria

- Transport chosen in [ADR-004](../decisions/ADR-004-video-preview-transport.md).
- GStreamer pipeline gains a `tee` branch for preview, low-bitrate transcode (800 kbps default, configurable).
- Segments / streams served by the supervisor from a tmpfs directory.
- Dashboard `<video>` element (HLS) or `<video srcObject>` (WebRTC) shows live feed within 3 s of page load, latency < 5 s.
- Disabling via `preview.enabled: false` removes the tee branch and /preview routes.

## Files touched

- `src/parrot_forwarder/forwarder/pipeline.py` (tee branch)
- `src/parrot_forwarder/supervisor/api/preview.py`
- `dashboard/src/components/Preview.*`

## How to verify

Open the dashboard against a mock forwarder using `videotestsrc`; confirm video renders.

## Notes

- Keep transcode on CPU for now; hardware accel (vaapi, nvenc, videotoolbox) is out of scope.
