from __future__ import annotations

from parrot_forwarder.supervisor import cli


def test_resolve_backend_auto_uses_none_when_real_worker_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_can_run_real_worker", lambda: False)
    assert cli._resolve_backend("auto") == "none"


def test_resolve_backend_auto_uses_subprocess_when_supported(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_can_run_real_worker", lambda: True)
    assert cli._resolve_backend("auto") == "subprocess"


def test_resolve_backend_honors_explicit_mock() -> None:
    assert cli._resolve_backend("mock") == "mock"
