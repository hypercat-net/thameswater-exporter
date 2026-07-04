import os
import sys

import pytest

from thameswater_exporter.config import Config


def _minimal_env(monkeypatch, **overrides):
    base = {
        "THAMESWATER_EMAIL": "user@example.com",
        "THAMESWATER_PASSWORD": "secret",
        "THAMESWATER_ACCOUNT_NUMBER": "123",
        "THAMESWATER_METER": "456",
        "THAMESWATER_EXPORTER_REMOTE_WRITE_URL": "http://mimir:9009/api/v1/push",
        "THAMESWATER_EXPORTER_MIMIR_TENANT": "utility",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    for key in (
        "THAMESWATER_EXPORTER_REMOTE_WRITE_URL",
        "THAMESWATER_EXPORTER_MIMIR_TENANT",
    ):
        if key not in overrides and key not in base:
            monkeypatch.delenv(key, raising=False)


def test_validate_rejects_alloy_receive_http_url(monkeypatch):
    _minimal_env(
        monkeypatch,
        THAMESWATER_EXPORTER_REMOTE_WRITE_URL="http://alloy:9999/api/v1/metrics/write",
    )
    cfg = Config()
    with pytest.raises(SystemExit):
        cfg.validate()


def test_validate_requires_tenant_for_mimir_push(monkeypatch):
    _minimal_env(monkeypatch)
    monkeypatch.delenv("THAMESWATER_EXPORTER_MIMIR_TENANT", raising=False)
    cfg = Config()
    with pytest.raises(SystemExit):
        cfg.validate()


def test_validate_accepts_mimir_push_with_tenant(monkeypatch):
    _minimal_env(monkeypatch)
    cfg = Config()
    cfg.validate()
