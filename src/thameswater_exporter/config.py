from __future__ import annotations

import logging
import os
import sys

from thameswater_exporter.constants import HOURLY_AVAILABILITY_DAYS

log = logging.getLogger(__name__)

DEFAULT_REMOTE_WRITE_URL = "http://mimir:9009/api/v1/push"


def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        log.error("Missing required environment variable: %s", name)
        sys.exit(2)
    return value


def _parse_labels(raw: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            log.warning(
                "Ignoring malformed THAMESWATER_EXPORTER_EXTRA_LABELS entry: %r", pair
            )
            continue
        key, value = pair.split("=", 1)
        labels[key.strip()] = value.strip()
    return labels


class Config:
    def __init__(self) -> None:
        self.email = _env("THAMESWATER_EMAIL", required=True)
        self.password = _env("THAMESWATER_PASSWORD", required=True)
        self.account_number = _env("THAMESWATER_ACCOUNT_NUMBER", required=True)
        self.meter = _env("THAMESWATER_METER", required=True)

        self.remote_write_url = _env(
            "THAMESWATER_EXPORTER_REMOTE_WRITE_URL",
            DEFAULT_REMOTE_WRITE_URL,
        )
        self.backfill_days = int(
            _env("THAMESWATER_EXPORTER_BACKFILL_DAYS", str(HOURLY_AVAILABILITY_DAYS))
        )
        self.chunk_days = int(_env("THAMESWATER_EXPORTER_CHUNK_DAYS", "7"))
        self.chunk_delay_seconds = float(
            _env("THAMESWATER_EXPORTER_CHUNK_DELAY_SECONDS", "1")
        )
        self.poll_interval = int(
            _env("THAMESWATER_EXPORTER_POLL_INTERVAL_SECONDS", "3600")
        )
        self.state_file = _env(
            "THAMESWATER_EXPORTER_STATE_FILE", "/data/state.json"
        )
        self.health_port = int(_env("THAMESWATER_EXPORTER_HEALTH_PORT", "9100"))
        self.log_level = _env("THAMESWATER_EXPORTER_LOG_LEVEL", "INFO").upper()

        self.rw_username = _env("THAMESWATER_EXPORTER_REMOTE_WRITE_USERNAME")
        self.rw_password = _env("THAMESWATER_EXPORTER_REMOTE_WRITE_PASSWORD")
        self.rw_bearer = _env("THAMESWATER_EXPORTER_REMOTE_WRITE_BEARER_TOKEN")
        self.tenant = _env("THAMESWATER_EXPORTER_MIMIR_TENANT")
        self.extra_labels = _parse_labels(
            _env("THAMESWATER_EXPORTER_EXTRA_LABELS", "")
        )

    def validate(self) -> None:
        url = self.remote_write_url or ""
        if "/api/v1/metrics/write" in url:
            log.error(
                "Grafana Alloy prometheus.receive_http is not supported; push "
                "directly to Mimir with THAMESWATER_EXPORTER_REMOTE_WRITE_URL="
                "http://<mimir-host>:9009/api/v1/push"
            )
            sys.exit(2)
        if "/api/v1/push" in url and not self.tenant:
            log.error(
                "THAMESWATER_EXPORTER_MIMIR_TENANT is required when pushing to "
                "Mimir (%s)",
                url,
            )
            sys.exit(2)

    def remote_write_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.tenant:
            headers["X-Scope-OrgID"] = self.tenant
        return headers

    def remote_write_auth(self) -> dict[str, str] | None:
        if self.rw_username and self.rw_password:
            return {"username": self.rw_username, "password": self.rw_password}
        if self.rw_bearer:
            return {"bearer_token": self.rw_bearer}
        return None
