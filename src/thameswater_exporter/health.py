from __future__ import annotations

import datetime
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from thameswaterapi import Account, Tariff

from thameswater_exporter import __version__
from thameswater_exporter.tariff import (
    water_standing_charge_per_day,
    wastewater_standing_charge_per_day,
)

log = logging.getLogger(__name__)


class Stats:
    def __init__(self) -> None:
        self.last_success_unixtime = 0.0
        self.last_run_unixtime = 0.0
        self.last_pushed_hour_unixtime = 0.0
        self.last_new_data_push_unixtime = 0.0
        self.last_pushed_reading_litres = 0.0
        self.tariff_clean_water_rate_per_m3 = 0.0
        self.tariff_wastewater_rate_per_m3 = 0.0
        self.tariff_water_standing_charge_per_day = 0.0
        self.tariff_wastewater_standing_charge_per_day = 0.0
        self.account_current_balance_gbp = 0.0
        self.account_payment_due_gbp = 0.0
        self.samples_pushed_total = 0
        self.push_errors_total = 0
        self.up = 0


STATS = Stats()


def update_data_metrics(
    last_pushed_hour: datetime.datetime | None,
    last_new_data_push_unixtime: float | None = None,
    last_pushed_reading_litres: float | None = None,
) -> None:
    if last_pushed_hour is not None:
        STATS.last_pushed_hour_unixtime = last_pushed_hour.astimezone(
            datetime.timezone.utc
        ).timestamp()
    if last_new_data_push_unixtime is not None:
        STATS.last_new_data_push_unixtime = last_new_data_push_unixtime
    if last_pushed_reading_litres is not None:
        STATS.last_pushed_reading_litres = last_pushed_reading_litres


def update_snapshot_metrics(
    *,
    tariff: Tariff | None = None,
    account: Account | None = None,
) -> None:
    if tariff is not None:
        STATS.tariff_clean_water_rate_per_m3 = tariff.clean_water_rate_per_m3
        STATS.tariff_wastewater_rate_per_m3 = tariff.wastewater_rate_per_m3
        STATS.tariff_water_standing_charge_per_day = water_standing_charge_per_day(
            tariff
        )
        STATS.tariff_wastewater_standing_charge_per_day = (
            wastewater_standing_charge_per_day(tariff)
        )
    if account is not None:
        STATS.account_current_balance_gbp = account.currentBalance
        STATS.account_payment_due_gbp = account.paymentDueAmount


def format_reading_litres(litres: float) -> str:
    if litres <= 0:
        return "unknown"
    return f"{litres:,.0f} L ({litres / 1000:,.3f} m³)"


def format_gbp(value: float, *, suffix: str = "") -> str:
    if value <= 0:
        return "unknown"
    return f"GBP {value:,.4f}{suffix}"


def _human_ago(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''} ago"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        if minutes:
            return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''} ago"
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days, hours = divmod(hours, 24)
    if hours:
        return f"{days} day{'s' if days != 1 else ''} {hours} hour{'s' if hours != 1 else ''} ago"
    return f"{days} day{'s' if days != 1 else ''} ago"


def format_unixtime(
    unixtime: float,
    *,
    now: datetime.datetime | None = None,
) -> str:
    if unixtime <= 0:
        return "never"
    now = now or datetime.datetime.now(datetime.timezone.utc)
    dt = datetime.datetime.fromtimestamp(unixtime, tz=datetime.timezone.utc)
    elapsed = max(0, int(now.timestamp() - unixtime))
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} UTC ({_human_ago(elapsed)})"


def render_status_page(*, now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    status = "OK" if STATS.up else "FAILED"
    lines = [
        f"thameswater-exporter {__version__}",
        "",
        f"Status: {status}",
        "",
        f"Last collection cycle:     {format_unixtime(STATS.last_success_unixtime, now=now)}",
        f"Last collection attempt:   {format_unixtime(STATS.last_run_unixtime, now=now)}",
        f"Last new data push:        {format_unixtime(STATS.last_new_data_push_unixtime, now=now)}",
        f"Newest reading hour:       {format_unixtime(STATS.last_pushed_hour_unixtime, now=now)}",
        f"Last published reading:    {format_reading_litres(STATS.last_pushed_reading_litres)}",
        "",
        f"Tariff volumetric rate:    {format_gbp(STATS.tariff_clean_water_rate_per_m3 + STATS.tariff_wastewater_rate_per_m3, suffix='/m³')}",
        f"Tariff clean water:        {format_gbp(STATS.tariff_clean_water_rate_per_m3, suffix='/m³')}",
        f"Tariff wastewater:         {format_gbp(STATS.tariff_wastewater_rate_per_m3, suffix='/m³')}",
        f"Water standing charge:     {format_gbp(STATS.tariff_water_standing_charge_per_day, suffix='/day')}",
        f"Wastewater standing:       {format_gbp(STATS.tariff_wastewater_standing_charge_per_day, suffix='/day')}",
        "",
        f"Account current balance:   {format_gbp(STATS.account_current_balance_gbp)}",
        f"Account payment due:       {format_gbp(STATS.account_payment_due_gbp)}",
        "",
        f"Samples pushed (since restart): {STATS.samples_pushed_total}",
        f"Push errors (since restart):    {STATS.push_errors_total}",
        "",
        "Prometheus metrics: /metrics",
        "Liveness probe:     /healthz",
    ]
    return "\n".join(lines) + "\n"


def render_self_metrics() -> str:
    return (
        "# HELP thameswater_exporter_up Whether the last collection cycle succeeded.\n"
        "# TYPE thameswater_exporter_up gauge\n"
        f"thameswater_exporter_up {STATS.up}\n"
        "# HELP thameswater_exporter_last_success_timestamp_seconds Unix time of the last collection cycle that completed without error (since restart).\n"
        "# TYPE thameswater_exporter_last_success_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_success_timestamp_seconds {STATS.last_success_unixtime}\n"
        "# HELP thameswater_exporter_last_run_timestamp_seconds Unix time of last collection attempt (since restart).\n"
        "# TYPE thameswater_exporter_last_run_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_run_timestamp_seconds {STATS.last_run_unixtime}\n"
        "# HELP thameswater_exporter_last_pushed_hour_timestamp_seconds Unix time of the newest finalised hour pushed to storage (high-water-mark; persisted across restarts).\n"
        "# TYPE thameswater_exporter_last_pushed_hour_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_pushed_hour_timestamp_seconds {STATS.last_pushed_hour_unixtime}\n"
        "# HELP thameswater_exporter_last_new_data_push_timestamp_seconds Unix time when the exporter last pushed one or more new finalised hours (persisted across restarts).\n"
        "# TYPE thameswater_exporter_last_new_data_push_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_new_data_push_timestamp_seconds {STATS.last_new_data_push_unixtime}\n"
        "# HELP thameswater_exporter_last_pushed_reading_litres Cumulative meter reading (litres) at the newest pushed hour (persisted across restarts).\n"
        "# TYPE thameswater_exporter_last_pushed_reading_litres gauge\n"
        f"thameswater_exporter_last_pushed_reading_litres {STATS.last_pushed_reading_litres}\n"
        "# HELP thameswater_exporter_samples_pushed_total Total samples pushed via remote_write since this process started (resets on restart).\n"
        "# TYPE thameswater_exporter_samples_pushed_total counter\n"
        f"thameswater_exporter_samples_pushed_total {STATS.samples_pushed_total}\n"
        "# HELP thameswater_exporter_push_errors_total Total failed collection/push cycles since this process started (resets on restart).\n"
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
            elif self.path in ("/", "/status"):
                body = render_status_page().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
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
    log.info(
        "Health/self-metrics server listening on :%d (/, /status, /healthz, /metrics)",
        port,
    )
