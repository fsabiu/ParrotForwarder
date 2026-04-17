"""
Tests for Prometheus metrics.

Parses the exposition format directly. No external ``promtool`` needed
(the CI runner doesn't have it) - we assert the shape that promtool
checks for: HELP, TYPE, labels, and stable naming.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from parrot_forwarder.metrics import PREFIX, Metrics, register_metrics_route


def test_default_metric_names_are_prefixed_and_have_help() -> None:
    metrics = Metrics()
    body = generate_latest(metrics.registry).decode("utf-8")
    for expected in (
        "parrot_forwarder_state",
        "parrot_forwarder_state_transitions_total",
        "parrot_forwarder_restarts_total",
        "parrot_forwarder_heartbeat_lag_seconds",
        "parrot_forwarder_pipeline_fps",
    ):
        assert expected in body, f"{expected} not exposed"
        assert f"# HELP {expected}" in body, f"no HELP for {expected}"
        assert f"# TYPE {expected}" in body, f"no TYPE for {expected}"


def test_record_state_transition_increments_counter_and_sets_gauge() -> None:
    metrics = Metrics()
    metrics.record_state_transition(from_state="READY", to_state="STREAMING", reason="pipeline_started")

    body = generate_latest(metrics.registry).decode("utf-8")
    # The counter sample with matching labels must be present with a value of 1.
    assert (
        'parrot_forwarder_state_transitions_total{from_state="READY",'
        'reason="pipeline_started",to_state="STREAMING"} 1.0'
    ) in body
    assert 'parrot_forwarder_state{name="STREAMING"} 1.0' in body
    assert 'parrot_forwarder_state{name="READY"} 0.0' in body


def test_record_restart_increments_counter() -> None:
    metrics = Metrics()
    metrics.record_restart(reason="pipeline_error")
    metrics.record_restart(reason="pipeline_error")
    body = generate_latest(metrics.registry).decode("utf-8")
    assert 'parrot_forwarder_restarts_total{reason="pipeline_error"} 2.0' in body


def test_record_heartbeat_sets_pipeline_metrics() -> None:
    metrics = Metrics()
    metrics.record_heartbeat(
        lag_seconds=0.5,
        pipeline_metrics={"fps": 29.97, "bitrate_kbps": 3200, "battery_percent": 82, "rssi_dbm": -60},
    )
    body = generate_latest(metrics.registry).decode("utf-8")
    assert "parrot_forwarder_heartbeat_lag_seconds 0.5" in body
    assert "parrot_forwarder_pipeline_fps 29.97" in body
    assert "parrot_forwarder_pipeline_bitrate_kbps 3200.0" in body
    assert "parrot_forwarder_battery_percent 82.0" in body
    assert "parrot_forwarder_rssi_dbm -60.0" in body


def test_heartbeat_ignores_missing_keys() -> None:
    metrics = Metrics()
    # Only sets fps; other gauges must stay at their default of 0.
    metrics.record_heartbeat(lag_seconds=0.1, pipeline_metrics={"fps": 15.0})
    body = generate_latest(metrics.registry).decode("utf-8")
    assert "parrot_forwarder_pipeline_fps 15.0" in body
    assert "parrot_forwarder_battery_percent 0.0" in body


def test_metrics_endpoint_is_mounted() -> None:
    app = FastAPI()
    metrics = Metrics()
    register_metrics_route(app, metrics)
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "parrot_forwarder_state" in response.text


def test_prefix_constant_matches_emitted_names() -> None:
    assert PREFIX == "parrot_forwarder_"
    assert generate_latest(Metrics().registry).decode("utf-8").count(PREFIX) > 0
