from __future__ import annotations

import datetime
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)


class Stats:
    def __init__(self) -> None:
        self.last_success_unixtime = 0.0
        self.last_run_unixtime = 0.0
        self.last_pushed_hour_unixtime = 0.0
        self.last_new_data_push_unixtime = 0.0
        self.samples_pushed_total = 0
        self.push_errors_total = 0
        self.up = 0


STATS = Stats()


def update_data_metrics(
    last_pushed_hour: datetime.datetime | None,
    last_new_data_push_unixtime: float | None = None,
) -> None:
    if last_pushed_hour is not None:
        STATS.last_pushed_hour_unixtime = last_pushed_hour.astimezone(
            datetime.timezone.utc
        ).timestamp()
    if last_new_data_push_unixtime is not None:
        STATS.last_new_data_push_unixtime = last_new_data_push_unixtime


def render_self_metrics() -> str:
    return (
        "# HELP thameswater_exporter_up Whether the last collection cycle succeeded.\n"
        "# TYPE thameswater_exporter_up gauge\n"
        f"thameswater_exporter_up {STATS.up}\n"
        "# HELP thameswater_exporter_last_success_timestamp_seconds Unix time of the last collection cycle that completed without error.\n"
        "# TYPE thameswater_exporter_last_success_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_success_timestamp_seconds {STATS.last_success_unixtime}\n"
        "# HELP thameswater_exporter_last_run_timestamp_seconds Unix time of last collection attempt.\n"
        "# TYPE thameswater_exporter_last_run_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_run_timestamp_seconds {STATS.last_run_unixtime}\n"
        "# HELP thameswater_exporter_last_pushed_hour_timestamp_seconds Unix time of the newest finalised hour pushed to storage (high-water-mark).\n"
        "# TYPE thameswater_exporter_last_pushed_hour_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_pushed_hour_timestamp_seconds {STATS.last_pushed_hour_unixtime}\n"
        "# HELP thameswater_exporter_last_new_data_push_timestamp_seconds Unix time when the exporter last pushed one or more new finalised hours.\n"
        "# TYPE thameswater_exporter_last_new_data_push_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_new_data_push_timestamp_seconds {STATS.last_new_data_push_unixtime}\n"
        "# HELP thameswater_exporter_samples_pushed_total Total samples pushed via remote_write.\n"
        "# TYPE thameswater_exporter_samples_pushed_total counter\n"
        f"thameswater_exporter_samples_pushed_total {STATS.samples_pushed_total}\n"
        "# HELP thameswater_exporter_push_errors_total Total failed collection/push cycles.\n"
        "# TYPE thameswater_exporter_push_errors_total counter\n"
        f"thameswater_exporter_push_errors_total {STATS.push_errors_total}\n"
    )


def start_health_server(port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                body = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
            elif self.path == "/metrics":
                body = render_self_metrics().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Health/self-metrics server listening on :%d (/healthz, /metrics)", port)
