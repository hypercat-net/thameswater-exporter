from __future__ import annotations

import logging
import os
import sys

from thameswater_exporter.constants import HOURLY_AVAILABILITY_DAYS

log = logging.getLogger(__name__)


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
            log.warning("Ignoring malformed EXTRA_LABELS entry: %r", pair)
            continue
        key, value = pair.split("=", 1)
        labels[key.strip()] = value.strip()
    return labels


class Config:
    def __init__(self) -> None:
        self.email = _env("EMAIL", required=True)
        self.password = _env("PASSWORD", required=True)
        self.account_number = _env("ACCOUNT_NUMBER", required=True)
        self.meter = _env("METER", required=True)

        self.remote_write_url = _env(
            "REMOTE_WRITE_URL", "http://alloy:9999/api/v1/metrics/write"
        )
        self.backfill_days = int(_env("BACKFILL_DAYS", str(HOURLY_AVAILABILITY_DAYS)))
        self.chunk_days = int(_env("CHUNK_DAYS", "7"))
        self.chunk_delay_seconds = float(_env("CHUNK_DELAY_SECONDS", "1"))
        self.poll_interval = int(_env("POLL_INTERVAL_SECONDS", "3600"))
        self.state_file = _env("STATE_FILE", "/data/state.json")
        self.health_port = int(_env("HEALTH_PORT", "9100"))
        self.log_level = _env("LOG_LEVEL", "INFO").upper()

        self.rw_username = _env("REMOTE_WRITE_USERNAME")
        self.rw_password = _env("REMOTE_WRITE_PASSWORD")
        self.rw_bearer = _env("REMOTE_WRITE_BEARER_TOKEN")
        self.tenant = _env("MIMIR_TENANT")
        self.extra_labels = _parse_labels(_env("EXTRA_LABELS", ""))

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
