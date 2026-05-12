# Spec: Configuration

## Sources and precedence

```
defaults (code) < config.yaml < environment vars < CLI flags
```

Effective config is logged at startup at INFO and returned from `GET /config`. Secrets (none today, but future-proof) are redacted.

## File location

- Default: `/etc/parrot-forwarder/config.yaml`
- Override: `--config /path/to.yaml`
- Dev: `./config.yaml` in working directory if present

## Schema

```yaml
drone:
  ip: "192.168.53.1"          # IPv4 of drone over USB tether
  model: "anafi"              # only "anafi" in v2

forwarder:
  srt_port: 8890              # main output
  klv_port: 12345             # local UDP, auto-incremented if busy
  telemetry_fps: 30
  video_fps: 30               # passthrough; drone decides actual rate

supervisor:
  http:
    bind: "127.0.0.1"         # NEVER expose externally in v2
    port: 8080
  auto_start: true            # start forwarding as soon as supervisor starts
  backoff:
    base_seconds: 1.0
    max_seconds: 60.0
    jitter_seconds: 1.0
  heartbeat:
    interval_seconds: 1.0
    timeout_seconds: 5.0

logging:
  level: "INFO"               # DEBUG|INFO|WARNING|ERROR
  format: "json"              # json|text
  file: "/var/log/parrot-forwarder/forwarder.log"
  rotation:
    max_bytes: 10485760       # 10 MB
    backup_count: 5

preview:
  enabled: true
  hls_segment_seconds: 2
  hls_playlist_size: 3
  bitrate_kbps: 800           # low-bitrate transcode, so main stream is untouched

metrics:
  enabled: true
  path: "/metrics"
```

## Environment variables

Each field maps to `PARROT_FORWARDER_<upper_snake_path>`. Example:

- `PARROT_FORWARDER_SUPERVISOR__HTTP__PORT=9090`

Double underscore separates nested keys.

## CLI flags

CLI keeps a minimal surface (the daemon is config-driven). Supported:

- `--config PATH` - alternate config file
- `--bind ADDR:PORT` - shortcut for `supervisor.http.bind/port`
- `--log-level LEVEL`
- `--no-auto-start` - override `supervisor.auto_start`
- `--drone-ip IP`

All others removed; users edit `config.yaml`.

## Reloadable fields

Fields marked reloadable can be changed without a restart (via SIGHUP):

- `logging.level`
- `forwarder.telemetry_fps`
- `metrics.enabled`

Non-reloadable changes require a restart. Attempting SIGHUP with a non-reloadable change is rejected and the old config stays.

## Validation

- On load: pydantic model, fail fast with a precise error citing the bad field.
- On reload: same validation; on failure, keep old config and log error, do not apply a partial.

## Secrets

None in v2. If v3 adds auth or external relay, use env vars only; never put secrets in `config.yaml`.

## Tests required

- Parse a valid YAML: match expected model.
- Env override: confirm precedence.
- CLI override: confirm precedence.
- Invalid YAML: descriptive error.
- Reload a valid change: applied without restart.
- Reload a non-reloadable change: rejected, old config retained.
