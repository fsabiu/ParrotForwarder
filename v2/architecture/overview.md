# v2 Architecture Overview

## Components

```
+-------------------------------------------------------------+
|  SUPERVISOR PROCESS  (main entry, long-lived)                |
|                                                             |
|  +---------------+   +------------------+                   |
|  | State Machine |<->| Health Monitor   |                   |
|  +---------------+   +------------------+                   |
|         |                                                   |
|         |  spawns / supervises                              |
|         v                                                   |
|  +---------------+   +------------------+  +-------------+  |
|  | Forwarder Mgr |   | IPC (UDS server) |  | HTTP Server |  |
|  +---------------+   +------------------+  +-------------+  |
|                              ^                    ^         |
|                              |                    |         |
+------------------------------|--------------------|---------+
                               |                    |
              JSON frames      |                    |  REST / WS / static
              over Unix domain |                    |  bound to 127.0.0.1
              socket           |                    v
                               |              +-----------+
                               |              | Browser   |
                               |              | Dashboard |
                               |              +-----------+
+------------------------------|------------------------------+
|  FORWARDER SUBPROCESS        v                              |
|                                                             |
|  +---------------+   +------------------+                   |
|  | IPC (UDS cli) |   | Heartbeat loop   |                   |
|  +---------------+   +------------------+                   |
|         |                                                   |
|         v                                                   |
|  +----------------+   +----------------+                    |
|  | Olympe Drone   |   | GStreamer mgr  |                    |
|  +----------------+   +----------------+                    |
|         |                      |                            |
|         v                      v                            |
|  +----------------+   +----------------+                    |
|  | Telemetry thr. |   | Video thread   |                    |
|  | (KLV -> UDP)   |   | (RTSP -> SRT,  |                    |
|  |                |   |  tee HLS)      |                    |
|  +----------------+   +----------------+                    |
+-------------------------------------------------------------+
          |                           |
          v                           v
  UDP :12345  (KLV)         SRT :8890  (MPEG-TS w/ muxed KLV)
                            HLS :8888  (dashboard preview)
```

## Why a separate forwarder subprocess

Three reasons:

1. **Crash isolation.** If Olympe or GStreamer crashes the Python interpreter (they do, rarely), the supervisor survives and restarts the child. In v1, any such crash kills the whole service and we rely on systemd to restart - with no structured reason and no recent telemetry in the dashboard.
2. **Restart without reinitializing HTTP/WS clients.** The dashboard keeps its WebSocket open while the forwarder cycles; users see "reconnecting drone..." instead of a blank page.
3. **Signal hygiene.** v1's `ParrotForwarder` installs SIGINT/SIGTERM handlers. A supervisor owns the signals; the child ignores them and exits on IPC command. This avoids the shutdown-race we saw in v1 when two signals arrive.

## Why Unix domain sockets for IPC

- Same host, no TCP overhead, no port to allocate or firewall.
- Newline-delimited JSON frames keep the protocol readable in `nc -U`.
- Permissions via filesystem (`0600`, supervisor owns the socket).

Alternative considered: stdin/stdout pipes. Rejected because we want the child to be crashable and restartable without rebuilding the pipe, and because bidirectional JSON framing over pipes is fiddly.

## State machine

Lives in the supervisor. The forwarder reports raw events (connected, disconnected, pipeline-error); the supervisor owns interpretation.

```
   +-------------------+
   |  DISCONNECTED     |<-------+
   +--------+----------+        |
            | start              |
            v                    |
   +-------------------+        |
   |  CONNECTING       |        |
   +--------+----------+        |
            | olympe-connected  |
            v                    |
   +-------------------+        |
   |  READY            |        |
   +--------+----------+        |
            | pipeline-started  |
            v                    |
   +-------------------+        |
   |  STREAMING        |--------+  (on terminal failure: DISCONNECTED)
   +---+-----+---------+        |
       |     | degrade-event    |
       |     v                  |
       |  +-----------+         |
       |  | DEGRADED  |         |  (pipeline running but unhealthy)
       |  +-----+-----+         |
       |        | timeout       |
       |        v               |
       |  +------------+        |
       +->| RESTARTING |--------+
          +------------+
```

Transitions, timeouts, and backoff in [state-machine.md](state-machine.md).

## Data flow

- **Telemetry**: Olympe callback -> KLV encoder -> UDP `:12345` (unchanged from v1). Also published to the supervisor over IPC, which fans out to WebSocket subscribers at a rate-limited 10 Hz.
- **Video main**: RTSP from drone -> GStreamer mux (video + KLV) -> SRT `:8890` (unchanged).
- **Video preview**: GStreamer `tee` branch -> low-bitrate transcode -> HLS segments served from supervisor's HTTP server at `/preview/stream.m3u8`. Main stream is untouched.

## Threading and async

- Supervisor is asyncio; FastAPI/uvicorn, UDS server, state machine, all cooperative.
- Forwarder stays threaded because Olympe and GStreamer both assume threads and don't like asyncio event loops in their callback paths. The heartbeat thread writes to UDS in small chunks.
- No shared memory between processes. All state transfer via IPC.

## Config layering

```
  defaults (in code)
    < config.yaml
    < environment vars (PARROT_FORWARDER_*)
    < CLI flags
```

Each layer logged at startup so the operator can see what took effect.
