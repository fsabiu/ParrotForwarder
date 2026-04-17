# ADR-004 - Video preview transport

**Status**: proposed
**Date**: 2026-04-17

## Context

The dashboard needs a live video preview. The main SRT stream already exists and must not be affected. Options:

1. **HLS** - GStreamer `hlssink2` writes segments; browser `<video>` plays them. Latency 4-10 s. Works everywhere without plugins or signalling.
2. **WebRTC** - push from GStreamer `webrtcbin`; browser `RTCPeerConnection`. Latency < 1 s. Requires SDP signalling over WS, ICE, STUN (localhost is fine, no STUN needed but still a dance).
3. **MJPEG** - motion-JPEG over HTTP. Trivial to implement. High bitrate, no hardware decode, ugly in 720p. Fine for tiny thumbnails, wrong for a live preview.

## Decision

HLS for v2.

## Consequences

Easier:
- Zero signalling. `GET /preview/stream.m3u8` is the whole API.
- Caching via tmpfs is straightforward.
- Works in Safari, Chrome, Firefox without Media Source Extensions shims for HLS.js on non-Safari browsers.

Harder:
- 4-10 s latency. The operator sees a slightly delayed feed; for "is the drone pointing the right way" this is fine, for fine-grained control it isn't. v2 scope is monitoring, not piloting.
- hls.js adds ~90 KB to the bundle for non-Safari browsers.

## Alternatives considered

- **WebRTC**: lower latency but adds ICE/SDP complexity and another GStreamer plugin (`webrtcbin`), which has its own ARM64 build quirks. Revisit in v3 if the use case demands sub-second latency.
- **MJPEG**: too expensive at 720p, visually poor. Rejected.
