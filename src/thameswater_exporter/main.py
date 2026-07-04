from __future__ import annotations

import logging
import signal
import threading

from prometheus_remote_writer import RemoteWriter

from thameswater_exporter.collector import collect_once
from thameswater_exporter.config import Config
from thameswater_exporter.health import STATS, start_health_server, update_data_metrics
from thameswater_exporter.state import load_meter_state

log = logging.getLogger(__name__)

_STOP = threading.Event()


def _handle_signal(signum, _frame):
    log.info("Received signal %s; shutting down after current cycle", signum)
    _STOP.set()


def main() -> None:
    cfg = Config()
    cfg.validate()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    start_health_server(cfg.health_port)

    state = load_meter_state(cfg.state_file, cfg.meter)
    update_data_metrics(state.last_pushed_hour, state.last_new_data_push_unixtime)

    writer = RemoteWriter(
        url=cfg.remote_write_url,
        headers=cfg.remote_write_headers() or None,
        auth=cfg.remote_write_auth(),
        timeout=30,
        retries=3,
        auto_convert_seconds_to_ms=False,
    )

    log.info(
        "Thames Water exporter started (poll every %ds, backfill %d days)",
        cfg.poll_interval,
        cfg.backfill_days,
    )

    while not _STOP.is_set():
        try:
            collect_once(cfg, writer, _STOP)
            STATS.up = 1
        except Exception:  # noqa: BLE001
            STATS.up = 0
            STATS.push_errors_total += 1
            log.exception("Collection cycle failed; will retry next interval")

        _STOP.wait(cfg.poll_interval)

    log.info("Exporter stopped")
