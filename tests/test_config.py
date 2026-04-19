"""
Unit tests for the layered config loader.

Covers every item called out in ``v2/specs/02-config.md`` under "Tests
required":

  - Parse a valid YAML: match expected model.
  - Env override: confirm precedence.
  - CLI override: confirm precedence.
  - Invalid YAML: descriptive error.
  - Reload a valid change: applied without restart.
  - Reload a non-reloadable change: rejected, old config retained.

The loader has zero import-time side effects, so these tests never touch
the real filesystem or the real environment - every input is injected.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from parrot_forwarder.config import (
    RELOADABLE_PATHS,
    Config,
    ConfigError,
    ReloadResult,
    load_config,
    reload_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def yaml_file(tmp_path: Path) -> Path:
    """A well-formed config.yaml exercising every top-level section."""
    body = dedent(
        """
        drone:
          ip: "10.0.0.42"
          model: "anafi"
        forwarder:
          srt_port: 9000
          klv_port: 12400
          telemetry_fps: 20
          video_fps: 30
        supervisor:
          http:
            bind: "127.0.0.1"
            port: 8081
          auto_start: false
          backoff:
            base_seconds: 2.0
            max_seconds: 120.0
            jitter_seconds: 0.5
          heartbeat:
            interval_seconds: 2.0
            timeout_seconds: 10.0
        logging:
          level: "WARNING"
          format: "text"
          file: "/tmp/pf.log"
          rotation:
            max_bytes: 2097152
            backup_count: 3
        preview:
          enabled: false
          hls_segment_seconds: 4
          hls_playlist_size: 6
          bitrate_kbps: 1200
        metrics:
          enabled: false
          path: "/prom"
        """
    ).strip()
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_defaults_when_no_layers_provided() -> None:
    cfg = load_config()
    assert cfg.drone.ip == "192.168.53.1"
    assert cfg.drone.video_ip is None
    assert cfg.drone.device_kind == "drone"
    assert cfg.drone.model == "anafi"
    assert cfg.forwarder.srt_port == 8890
    assert cfg.forwarder.klv_port == 12345
    assert cfg.forwarder.telemetry_fps == 10
    assert cfg.supervisor.http.bind == "127.0.0.1"
    assert cfg.supervisor.http.port == 8080
    assert cfg.supervisor.auto_start is True
    assert cfg.logging.level == "INFO"
    assert cfg.logging.format == "json"
    assert cfg.metrics.enabled is True
    assert cfg.recording.enabled is True
    assert cfg.recording.path == "/recordings"
    assert cfg.recording.auto_on_takeoff is False
    assert cfg.recording.max_bytes_per_file == 10 * 1024 * 1024 * 1024
    assert cfg.recording.retention_days == 90


# ---------------------------------------------------------------------------
# Valid YAML
# ---------------------------------------------------------------------------


def test_valid_yaml_maps_to_model(yaml_file: Path) -> None:
    cfg = load_config(path=yaml_file)
    assert cfg.drone.ip == "10.0.0.42"
    assert cfg.drone.video_ip is None
    assert cfg.drone.device_kind == "drone"
    assert cfg.forwarder.srt_port == 9000
    assert cfg.forwarder.telemetry_fps == 20
    assert cfg.supervisor.http.port == 8081
    assert cfg.supervisor.auto_start is False
    assert cfg.supervisor.backoff.max_seconds == 120.0
    assert cfg.logging.level == "WARNING"
    assert cfg.logging.format == "text"
    assert cfg.logging.rotation.max_bytes == 2_097_152
    assert cfg.preview.enabled is False
    assert cfg.preview.bitrate_kbps == 1200
    assert cfg.metrics.enabled is False
    assert cfg.metrics.path == "/prom"


def test_empty_yaml_is_equivalent_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    cfg = load_config(path=path)
    assert cfg == Config()


# ---------------------------------------------------------------------------
# Env precedence
# ---------------------------------------------------------------------------


def test_env_overrides_yaml(yaml_file: Path) -> None:
    env = {
        "PARROT_FORWARDER_SUPERVISOR__HTTP__PORT": "9090",
        "PARROT_FORWARDER_LOGGING__LEVEL": "DEBUG",
        "PARROT_FORWARDER_METRICS__ENABLED": "true",
    }
    cfg = load_config(path=yaml_file, env=env)
    assert cfg.supervisor.http.port == 9090, "env must override yaml"
    assert cfg.logging.level == "DEBUG"
    assert cfg.metrics.enabled is True


def test_env_is_ignored_without_prefix() -> None:
    env = {"SUPERVISOR__HTTP__PORT": "9090"}
    cfg = load_config(env=env)
    assert cfg.supervisor.http.port == 8080


def test_env_coerces_booleans_and_ints() -> None:
    env = {
        "PARROT_FORWARDER_SUPERVISOR__AUTO_START": "false",
        "PARROT_FORWARDER_FORWARDER__SRT_PORT": "9999",
        "PARROT_FORWARDER_SUPERVISOR__BACKOFF__BASE_SECONDS": "0.5",
    }
    cfg = load_config(env=env)
    assert cfg.supervisor.auto_start is False
    assert cfg.forwarder.srt_port == 9999
    assert cfg.supervisor.backoff.base_seconds == 0.5


def test_env_malformed_path_rejected() -> None:
    env = {"PARROT_FORWARDER_SUPERVISOR____PORT": "9090"}
    with pytest.raises(ConfigError, match="empty path segment"):
        load_config(env=env)


# ---------------------------------------------------------------------------
# CLI precedence
# ---------------------------------------------------------------------------


def test_cli_overrides_env_and_yaml(yaml_file: Path) -> None:
    env = {"PARROT_FORWARDER_SUPERVISOR__HTTP__PORT": "9090"}
    cli = {"supervisor": {"http": {"port": 7777}}}
    cfg = load_config(path=yaml_file, env=env, cli_overrides=cli)
    assert cfg.supervisor.http.port == 7777, "cli must beat env and yaml"


def test_cli_accepts_dotted_keys(yaml_file: Path) -> None:
    cli = {"supervisor.http.port": 7000, "drone.ip": "172.16.0.1"}
    cfg = load_config(path=yaml_file, cli_overrides=cli)
    assert cfg.supervisor.http.port == 7000
    assert cfg.drone.ip == "172.16.0.1"


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


def test_invalid_yaml_produces_descriptive_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("drone: {\n  ip: 10.0.0.1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path=path)
    assert "Invalid YAML" in str(excinfo.value)
    assert str(path) in str(excinfo.value)


def test_non_mapping_yaml_rejected(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(path=path)


def test_unknown_field_rejected() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(cli_overrides={"drone": {"unknown_field": 1}})
    # The error names the offending field.
    assert "unknown_field" in str(excinfo.value)


def test_invalid_enum_value_rejected() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(cli_overrides={"logging": {"level": "TRACE"}})
    assert "logging.level" in str(excinfo.value)


def test_out_of_range_port_rejected() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(cli_overrides={"supervisor": {"http": {"port": 0}}})
    assert "supervisor.http.port" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Reload semantics
# ---------------------------------------------------------------------------


def test_reload_with_only_reloadable_change_applies() -> None:
    old = load_config()
    new = load_config(cli_overrides={"logging": {"level": "DEBUG"}})
    result = reload_config(old, new)
    assert isinstance(result, ReloadResult)
    assert result.applied == ("logging.level",)
    assert result.rejected == {}
    assert result.new_config is new
    assert result.new_config.logging.level == "DEBUG"


def test_reload_with_multiple_reloadable_changes_applies_all() -> None:
    old = load_config()
    new = load_config(
        cli_overrides={
            "logging": {"level": "DEBUG"},
            "forwarder": {"telemetry_fps": 5},
            "metrics": {"enabled": False},
        }
    )
    result = reload_config(old, new)
    assert result.rejected == {}
    assert set(result.applied) == {
        "logging.level",
        "forwarder.telemetry_fps",
        "metrics.enabled",
    }
    assert result.new_config is new


def test_reload_with_non_reloadable_change_is_rejected_wholesale() -> None:
    old = load_config()
    new = load_config(
        cli_overrides={
            "supervisor": {"http": {"port": 9090}},  # NOT reloadable
            "logging": {"level": "DEBUG"},  # reloadable - must NOT leak through
        }
    )
    result = reload_config(old, new)
    assert result.new_config is old, "reload must be all-or-nothing"
    assert "supervisor.http.port" in result.rejected
    assert "logging.level" not in result.applied
    # The reloadable-but-rejected change is NOT reported in rejected either;
    # the spec only requires that the whole reload is dropped.
    assert result.applied == ()


def test_reload_with_no_changes_is_noop() -> None:
    old = load_config()
    new = load_config()
    result = reload_config(old, new)
    assert result.applied == ()
    assert result.rejected == {}
    assert result.new_config is new


def test_reloadable_paths_set_matches_spec() -> None:
    """Spec 02-config.md names these three fields as reloadable."""
    assert RELOADABLE_PATHS == frozenset(
        {
            "logging.level",
            "forwarder.telemetry_fps",
            "metrics.enabled",
        }
    )


def test_recording_fields_are_not_reloadable() -> None:
    """All recording fields affect the ffmpeg child process or disk layout."""
    old = load_config()
    new = load_config(cli_overrides={"recording": {"path": "/tmp/recs"}})
    result = reload_config(old, new)
    assert result.new_config is old
    assert "recording.path" in result.rejected


def test_recording_from_yaml(tmp_path: Path) -> None:
    body = dedent(
        """
        recording:
          enabled: false
          path: "/data/recs"
          auto_on_takeoff: true
          max_bytes_per_file: 1073741824
          retention_days: 7
        """
    ).strip()
    path = tmp_path / "r.yaml"
    path.write_text(body, encoding="utf-8")
    cfg = load_config(path=path)
    assert cfg.recording.enabled is False
    assert cfg.recording.path == "/data/recs"
    assert cfg.recording.auto_on_takeoff is True
    assert cfg.recording.max_bytes_per_file == 1_073_741_824
    assert cfg.recording.retention_days == 7


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


def test_load_config_does_not_read_real_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """``env=None`` means no env layer - real os.environ must be ignored."""
    monkeypatch.setenv("PARROT_FORWARDER_SUPERVISOR__HTTP__PORT", "31337")
    cfg = load_config()
    assert cfg.supervisor.http.port == 8080
