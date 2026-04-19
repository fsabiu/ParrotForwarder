"""
Layered configuration loader for ParrotForwarder v2.

Precedence (lowest to highest):

    defaults (in code)
      < config.yaml
      < environment vars (PARROT_FORWARDER_*)
      < CLI overrides

The public entry point is :func:`load_config`. It is deliberately free of
module-import-time side effects: nothing reads the filesystem, the env,
or the CLI unless the caller passes the corresponding argument in. This
keeps the loader trivially unit-testable.

Reloadable fields are declared in :data:`RELOADABLE_PATHS`. Attempting to
change any non-reloadable field via :func:`reload_config` causes the whole
reload to be rejected; the spec forbids applying a partial reload.

See ``v2/specs/02-config.md`` for the authoritative schema.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

try:
    import yaml
except ImportError as exc:  # pragma: no cover - PyYAML is a hard runtime dep
    raise ImportError(
        "PyYAML is required for config loading. Install with `pip install pyyaml`."
    ) from exc


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

# Every sub-model is frozen and forbids extras: typos in config files should
# fail fast with a field-qualified error rather than silently be ignored.
_STRICT = ConfigDict(extra="forbid", frozen=True)


class DroneConfig(BaseModel):
    """Drone connection parameters."""

    model_config = _STRICT

    ip: str = Field(
        default="192.168.53.1",
        description="IPv4 of the Olympe control endpoint (direct drone or SkyController)",
    )
    video_ip: str | None = Field(
        default=None,
        description="Optional IPv4 of the RTSP video endpoint; defaults to drone.ip",
    )
    device_kind: Literal["drone", "skycontroller"] = Field(
        default="drone",
        description="How Olympe should connect to drone.ip",
    )
    model: Literal["anafi"] = Field(default="anafi", description="Only 'anafi' is supported in v2")


class ForwarderConfig(BaseModel):
    """Forwarder subprocess parameters (video + telemetry)."""

    model_config = _STRICT

    srt_port: int = Field(default=8890, ge=1, le=65535, description="Main SRT output port")
    klv_port: int = Field(
        default=12345,
        ge=1,
        le=65535,
        description="Local UDP port for KLV; auto-incremented by runtime if busy",
    )
    telemetry_fps: int = Field(default=10, ge=1, le=100, description="Telemetry/KLV rate (Hz)")
    video_fps: int = Field(
        default=30,
        ge=1,
        le=120,
        description="Informational; the drone determines the actual rate",
    )


class HttpConfig(BaseModel):
    """Supervisor HTTP server bind parameters."""

    model_config = _STRICT

    bind: str = Field(
        default="127.0.0.1",
        description="NEVER expose externally in v2; no auth is present",
    )
    port: int = Field(default=8080, ge=1, le=65535)


class BackoffConfig(BaseModel):
    """Supervisor restart backoff policy."""

    model_config = _STRICT

    base_seconds: float = Field(default=1.0, gt=0.0)
    max_seconds: float = Field(default=60.0, gt=0.0)
    jitter_seconds: float = Field(default=1.0, ge=0.0)


class HeartbeatConfig(BaseModel):
    """Supervisor <-> forwarder heartbeat parameters."""

    model_config = _STRICT

    interval_seconds: float = Field(default=1.0, gt=0.0)
    timeout_seconds: float = Field(default=5.0, gt=0.0)


class SupervisorConfig(BaseModel):
    """Supervisor process parameters."""

    model_config = _STRICT

    http: HttpConfig = Field(default_factory=HttpConfig)
    auto_start: bool = Field(
        default=True,
        description="Start forwarding as soon as the supervisor comes up",
    )
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class RotationConfig(BaseModel):
    """Log file rotation parameters."""

    model_config = _STRICT

    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=5, ge=0)


class LoggingConfig(BaseModel):
    """Structured logging parameters."""

    model_config = _STRICT

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    format: Literal["json", "text"] = Field(default="json")
    file: str = Field(default="/var/log/parrot-forwarder/forwarder.log")
    rotation: RotationConfig = Field(default_factory=RotationConfig)


class PreviewConfig(BaseModel):
    """Dashboard HLS video preview parameters."""

    model_config = _STRICT

    enabled: bool = Field(default=True)
    hls_segment_seconds: int = Field(default=2, ge=1, le=10)
    hls_playlist_size: int = Field(default=3, ge=1, le=20)
    bitrate_kbps: int = Field(
        default=800,
        ge=100,
        le=10_000,
        description="Low-bitrate preview transcode; main stream is untouched",
    )


class MetricsConfig(BaseModel):
    """Prometheus metrics parameters."""

    model_config = _STRICT

    enabled: bool = Field(default=True)
    path: str = Field(default="/metrics")


class RecordingConfig(BaseModel):
    """Recording subprocess parameters.

    Recording runs as a sibling ``ffmpeg`` process that consumes the
    forwarder's own SRT output and writes an MPEG-TS file preserving both
    the H.264 video stream and the KLV data stream. Files land under
    ``path`` in a deterministic ``YYYY-MM-DD/<mission>/<drone>_<session>_<start>.ts``
    layout and are indexed in ``<path>/index.db``.

    None of these fields are reloadable at runtime: they affect the child
    subprocess command line and the file layout on disk.
    """

    model_config = _STRICT

    enabled: bool = Field(
        default=True,
        description="Master switch for the recording feature (API still responds when false)",
    )
    path: str = Field(
        default="/recordings",
        description="Directory where .ts files, sidecars, and index.db live",
    )
    auto_on_takeoff: bool = Field(
        default=False,
        description="Start recording automatically on takeoff; stop on landing",
    )
    max_bytes_per_file: int = Field(
        default=10 * 1024 * 1024 * 1024,  # 10 GiB
        ge=1024 * 1024,
        description="Safety cap on a single recording; recorder stops gracefully at this size",
    )
    retention_days: int = Field(
        default=90,
        ge=0,
        description="0 disables retention; otherwise unflagged recordings older than this are deleted",
    )


class Config(BaseModel):
    """Top-level ParrotForwarder v2 configuration.

    Construct via :func:`load_config` - do not instantiate directly unless
    writing a test that wants a freshly-defaulted config.
    """

    model_config = _STRICT

    drone: DroneConfig = Field(default_factory=DroneConfig)
    forwarder: ForwarderConfig = Field(default_factory=ForwarderConfig)
    supervisor: SupervisorConfig = Field(default_factory=SupervisorConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)


# ---------------------------------------------------------------------------
# Reloadable field policy
# ---------------------------------------------------------------------------

#: Dotted paths of fields that SIGHUP may change at runtime. Any other change
#: attempted via :func:`reload_config` rejects the entire reload.
RELOADABLE_PATHS: frozenset[str] = frozenset(
    {
        "logging.level",
        "forwarder.telemetry_fps",
        "metrics.enabled",
    }
)


class ReloadResult(BaseModel):
    """Outcome of a :func:`reload_config` call.

    - ``applied`` holds the dotted paths whose values were accepted.
    - ``rejected`` maps dotted paths to a human-readable rejection reason.
    - ``new_config`` is the config to use going forward: either the reloaded
      config (when all changes are reloadable) or the original, unchanged
      config (when any change is non-reloadable).
    """

    model_config = ConfigDict(frozen=True)

    applied: tuple[str, ...] = ()
    rejected: dict[str, str] = Field(default_factory=dict)
    new_config: Config


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised for any configuration error: bad YAML, bad env, bad CLI, bad schema."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_ENV_PREFIX = "PARROT_FORWARDER_"


def load_config(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> Config:
    """Load config applying the documented layering.

    Args:
        path: Optional path to ``config.yaml``. If ``None`` the YAML layer
            is skipped and defaults are used. The caller decides the
            filesystem search (``/etc/parrot-forwarder/config.yaml``,
            ``./config.yaml``, etc.).
        env: Mapping used as the environment layer. Pass ``os.environ``
            in production or a plain ``dict`` in tests. If ``None``, no
            env vars are considered.
        cli_overrides: Nested dict of CLI overrides, e.g.
            ``{"supervisor": {"http": {"port": 9090}}}``. Flat dotted-key
            dicts like ``{"supervisor.http.port": 9090}`` are also accepted.

    Returns:
        A validated :class:`Config`.

    Raises:
        ConfigError: on invalid YAML, invalid env var, invalid CLI
            override, or schema validation failure. The message always
            names the offending field path.
    """
    yaml_layer = _load_yaml_layer(path)
    env_layer = _parse_env_layer(env or {})
    cli_layer = _normalize_cli_overrides(cli_overrides or {})

    merged: dict[str, Any] = {}
    for layer in (yaml_layer, env_layer, cli_layer):
        _deep_merge(merged, layer)

    try:
        return Config.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


def reload_config(old: Config, new: Config) -> ReloadResult:
    """Compute the effect of reloading ``new`` on top of ``old``.

    If every changed field is in :data:`RELOADABLE_PATHS`, the reload is
    accepted and ``new_config`` is ``new``. Otherwise the reload is
    rejected wholesale - ``new_config`` is ``old`` - and every
    non-reloadable change is recorded in ``rejected``.

    Args:
        old: Currently-active config.
        new: Proposed config, already validated (i.e. loaded via
            :func:`load_config`).

    Returns:
        A :class:`ReloadResult` describing what was (or was not) applied.
    """
    changes = _diff_config(old, new)

    reloadable_changes: list[str] = []
    non_reloadable_changes: dict[str, str] = {}

    for dotted in changes:
        if dotted in RELOADABLE_PATHS:
            reloadable_changes.append(dotted)
        else:
            non_reloadable_changes[dotted] = (
                f"Field '{dotted}' is not reloadable; restart required."
            )

    if non_reloadable_changes:
        return ReloadResult(
            applied=(),
            rejected=non_reloadable_changes,
            new_config=old,
        )

    return ReloadResult(
        applied=tuple(sorted(reloadable_changes)),
        rejected={},
        new_config=new,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_yaml_layer(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config file '{path}': {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in '{path}': {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Invalid YAML in '{path}': top-level document must be a mapping, got {type(data).__name__}"
        )
    return data


def _parse_env_layer(env: Mapping[str, str]) -> dict[str, Any]:
    """Turn ``PARROT_FORWARDER_A__B__C=v`` into ``{"a": {"b": {"c": "v"}}}``."""
    layer: dict[str, Any] = {}
    for key, value in env.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        suffix = key[len(_ENV_PREFIX) :]
        if not suffix:
            raise ConfigError(f"Empty env var name after prefix: '{key}'")
        parts = [p.lower() for p in suffix.split("__")]
        if any(p == "" for p in parts):
            raise ConfigError(
                f"Malformed env var '{key}': empty path segment in '{suffix}'"
            )
        _assign_nested(layer, parts, _coerce_scalar(value))
    return layer


def _normalize_cli_overrides(cli: Mapping[str, Any]) -> dict[str, Any]:
    """Accept either nested dicts or dotted-key dicts as CLI overrides."""
    layer: dict[str, Any] = {}
    for key, value in cli.items():
        if "." in key:
            parts = key.split(".")
            if any(p == "" for p in parts):
                raise ConfigError(f"Malformed CLI override key '{key}'")
            _assign_nested(layer, parts, value)
        else:
            if isinstance(value, dict):
                # Nested value: deep-merge it in under the flat key.
                _deep_merge(layer.setdefault(key, {}), value)
            else:
                layer[key] = value
    return layer


def _assign_nested(target: dict[str, Any], parts: Iterable[str], value: Any) -> None:
    parts = list(parts)
    cursor = target
    for segment in parts[:-1]:
        existing = cursor.get(segment)
        if existing is None:
            existing = {}
            cursor[segment] = existing
        elif not isinstance(existing, dict):
            raise ConfigError(
                f"Cannot set '{'.'.join(parts)}': '{segment}' is a scalar, not a mapping"
            )
        cursor = existing
    cursor[parts[-1]] = value


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> None:
    """Recursively merge ``overlay`` into ``base`` in place; overlay wins."""
    for key, value in overlay.items():
        if (
            isinstance(value, dict)
            and key in base
            and isinstance(base[key], dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _coerce_scalar(raw: str) -> Any:
    """Coerce env-var strings into YAML-compatible scalars.

    We accept the same spellings the YAML layer would: booleans, integers,
    floats, and null. Anything else stays a string - pydantic applies its
    own validators (e.g. Literal membership) on top.
    """
    text = raw.strip()
    lowered = text.lower()
    if lowered in {"null", "none", "~", ""}:
        return None
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return raw


def _diff_config(old: Config, new: Config) -> list[str]:
    """Return dotted paths whose values differ between ``old`` and ``new``."""
    old_dump = old.model_dump()
    new_dump = new.model_dump()
    return sorted(_dict_diff(old_dump, new_dump, prefix=""))


def _dict_diff(old: Mapping[str, Any], new: Mapping[str, Any], prefix: str) -> list[str]:
    diffs: list[str] = []
    keys = set(old.keys()) | set(new.keys())
    for key in keys:
        path = f"{prefix}.{key}" if prefix else key
        o = old.get(key)
        n = new.get(key)
        if isinstance(o, dict) and isinstance(n, dict):
            diffs.extend(_dict_diff(o, n, path))
        elif o != n:
            diffs.append(path)
    return diffs


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid configuration:"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "")
        lines.append(f"  - {loc}: {msg}")
    return "\n".join(lines)
