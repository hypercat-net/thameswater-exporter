"""Thames Water -> Prometheus remote_write exporter.

Thames Water smart-meter readings are NOT real time: recent hours arrive a day
or two late and are flagged ``IsEstimated`` until finalised. A normal Prometheus
scrape would stamp every value with *scrape time*, putting your water usage at
the wrong point on the timeline.

This exporter instead pushes each hourly reading via the Prometheus remote_write
protocol with the sample's *real* ``hour_start`` timestamp. It tracks a
high-water-mark per meter so it only sends new, finalised (non-estimated) hours,
in strictly increasing timestamp order. Hourly data is only available for the
last 7 days from Thames Water.

Topology (default):

    Thames Water API -> this exporter -> Alloy (prometheus.receive_http)
                                       -> Alloy (prometheus.remote_write) -> Mimir

See README.md. The config/ directory is for the local docker-compose test stack.
"""

from __future__ import annotations

import os
import sys
import json
import time
import signal
import logging
import datetime
import threading
import zoneinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_remote_writer import RemoteWriter
from thameswaterapi import ThamesWater

from tw_readings import Measurement, lines_to_measurements


LONDON = zoneinfo.ZoneInfo("Europe/London")

# Thames Water only serves *hourly* readings for roughly the last 7 days
# (the "daily, by hour" view). Older data is available only at coarser
# resolution, so there is no point requesting hourly beyond this window, and if
# the exporter is down longer than this the missed hours are unrecoverable.
HOURLY_AVAILABILITY_DAYS = 7

READING_METRIC = "thameswater_meter_reading_litres_total"
USAGE_METRIC = "thameswater_hourly_usage_litres"

log = logging.getLogger("thameswater_exporter")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        log.error("Missing required environment variable: %s", name)
        sys.exit(2)
    return value


class Config:
    def __init__(self) -> None:
        self.email = _env("EMAIL", required=True)
        self.password = _env("PASSWORD", required=True)
        self.account_number = _env("ACCOUNT_NUMBER", required=True)
        self.meter = _env("METER", required=True)

        self.remote_write_url = _env(
            "REMOTE_WRITE_URL", "http://alloy:9999/api/v1/metrics/write"
        )
        # Hourly data only goes back ~7 days, so backfilling more is pointless.
        self.backfill_days = int(_env("BACKFILL_DAYS", str(HOURLY_AVAILABILITY_DAYS)))
        # Thames Water only serves hourly data in a limited span per request, so
        # the backfill is fetched in bounded windows rather than one big call.
        self.chunk_days = int(_env("CHUNK_DAYS", "7"))
        # Be gentle with the API between successive chunk requests.
        self.chunk_delay_seconds = float(_env("CHUNK_DELAY_SECONDS", "1"))
        self.poll_interval = int(_env("POLL_INTERVAL_SECONDS", "3600"))
        self.state_file = _env("STATE_FILE", "/data/state.json")
        self.health_port = int(_env("HEALTH_PORT", "8000"))
        self.log_level = _env("LOG_LEVEL", "INFO").upper()

        # Optional auth to the remote_write endpoint (e.g. if Alloy is behind a proxy).
        self.rw_username = _env("REMOTE_WRITE_USERNAME")
        self.rw_password = _env("REMOTE_WRITE_PASSWORD")
        self.rw_bearer = _env("REMOTE_WRITE_BEARER_TOKEN")
        # Sent only for direct-to-Mimir setups; Alloy's receive_http ignores headers.
        self.tenant = _env("MIMIR_TENANT")

        # Extra static labels, e.g. "location=home,env=prod".
        self.extra_labels = _parse_labels(_env("EXTRA_LABELS", ""))

    def remote_write_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        # Only meaningful for direct-to-Mimir setups; Alloy's receive_http drops it.
        if self.tenant:
            headers["X-Scope-OrgID"] = self.tenant
        return headers

    def remote_write_auth(self) -> dict[str, str] | None:
        if self.rw_username and self.rw_password:
            return {"username": self.rw_username, "password": self.rw_password}
        if self.rw_bearer:
            return {"bearer_token": self.rw_bearer}
        return None


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


# --------------------------------------------------------------------------- #
# State (per meter: high-water-mark of last pushed hour)
# --------------------------------------------------------------------------- #
class MeterState:
    def __init__(self, last_pushed_hour: datetime.datetime | None) -> None:
        self.last_pushed_hour = last_pushed_hour


def load_meter_state(state_file: str, meter: str) -> MeterState:
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        return MeterState(None)
    except (OSError, ValueError) as exc:
        log.warning("Could not read state file %s: %s", state_file, exc)
        return MeterState(None)

    iso = state.get("meters", {}).get(str(meter), {}).get("last_pushed_hour")
    return MeterState(
        datetime.datetime.fromisoformat(iso) if iso else None,
    )


def save_meter_state(
    state_file: str,
    meter: str,
    hour_start: datetime.datetime,
) -> None:
    state: dict = {"meters": {}}
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (FileNotFoundError, ValueError):
        pass

    state.setdefault("meters", {})[str(meter)] = {
        "last_pushed_hour": hour_start.astimezone(datetime.timezone.utc).isoformat(),
    }

    parent = os.path.dirname(state_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{state_file}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, state_file)


# --------------------------------------------------------------------------- #
# Self-observability (exporter health, scrapeable in real time)
# --------------------------------------------------------------------------- #
class Stats:
    def __init__(self) -> None:
        self.last_success_unixtime = 0.0
        self.last_run_unixtime = 0.0
        self.samples_pushed_total = 0
        self.push_errors_total = 0
        self.up = 0


STATS = Stats()


def _start_health_server(port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib naming)
            if self.path == "/healthz":
                body = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
            elif self.path == "/metrics":
                body = _render_self_metrics().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence default request logging
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Health/self-metrics server listening on :%d (/healthz, /metrics)", port)


def _render_self_metrics() -> str:
    return (
        "# HELP thameswater_exporter_up Whether the last collection cycle succeeded.\n"
        "# TYPE thameswater_exporter_up gauge\n"
        f"thameswater_exporter_up {STATS.up}\n"
        "# HELP thameswater_exporter_last_success_timestamp_seconds Unix time of last successful push.\n"
        "# TYPE thameswater_exporter_last_success_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_success_timestamp_seconds {STATS.last_success_unixtime}\n"
        "# HELP thameswater_exporter_last_run_timestamp_seconds Unix time of last collection attempt.\n"
        "# TYPE thameswater_exporter_last_run_timestamp_seconds gauge\n"
        f"thameswater_exporter_last_run_timestamp_seconds {STATS.last_run_unixtime}\n"
        "# HELP thameswater_exporter_samples_pushed_total Total samples pushed via remote_write.\n"
        "# TYPE thameswater_exporter_samples_pushed_total counter\n"
        f"thameswater_exporter_samples_pushed_total {STATS.samples_pushed_total}\n"
        "# HELP thameswater_exporter_push_errors_total Total failed collection/push cycles.\n"
        "# TYPE thameswater_exporter_push_errors_total counter\n"
        f"thameswater_exporter_push_errors_total {STATS.push_errors_total}\n"
    )


# --------------------------------------------------------------------------- #
# Core collection logic
# --------------------------------------------------------------------------- #
def select_new_final_measurements(
    measurements: list[Measurement],
    high_water_mark: datetime.datetime | None,
) -> list[Measurement]:
    """Return the contiguous run of finalised hours after the high-water-mark.

    Recent hours are estimated and may be corrected later, which would collide
    with an already-ingested sample at the same timestamp. To stay safe we only
    advance through hours that are *not* estimated, stopping at the first
    estimated (or already-seen) hour.
    """
    ordered = sorted(measurements, key=lambda m: m.hour_start)
    selected: list[Measurement] = []
    for m in ordered:
        if high_water_mark is not None and m.hour_start <= high_water_mark:
            continue
        if m.is_estimated:
            break  # not final yet -> stop; pick it up on a later cycle
        selected.append(m)
    return selected


def build_write_payload(
    measurements: list[Measurement],
    base_labels: dict[str, str],
) -> list[dict]:
    """Build two timestamp-ordered series: meter reading (Read) and hourly usage."""
    timestamps = [
        int(m.hour_start.astimezone(datetime.timezone.utc).timestamp() * 1000)
        for m in measurements
    ]
    serial = measurements[-1].serial if measurements else ""
    labels = {**base_labels}
    if serial:
        labels["serial"] = serial

    return [
        {
            "metric": {"__name__": READING_METRIC, **labels},
            "values": [float(m.total) for m in measurements],
            "timestamps": list(timestamps),
        },
        {
            "metric": {"__name__": USAGE_METRIC, **labels},
            "values": [float(m.usage) for m in measurements],
            "timestamps": list(timestamps),
        },
    ]


def compute_fetch_window(
    now_london: datetime.datetime,
    hwm: datetime.datetime | None,
    backfill_days: int,
) -> "tuple[datetime.date, datetime.date, bool]":
    """Work out the date range to request, clamped to the hourly availability window.

    Hourly data only exists for the last ~7 days, so we never request earlier
    than that. Returns ``(start_date, end_date, gap)`` where ``gap`` is True if
    the high-water-mark is older than the hourly window, meaning some hours have
    aged out and can no longer be retrieved.
    """
    end_date = now_london.date()
    horizon_start = (
        now_london - datetime.timedelta(days=HOURLY_AVAILABILITY_DAYS - 1)
    ).date()

    if hwm is None:
        requested = (now_london - datetime.timedelta(days=backfill_days - 1)).date()
        return max(requested, horizon_start), end_date, False

    # Re-fetch from the day of the high-water-mark so we pick up the following
    # hours; selection drops anything already pushed.
    start_date = hwm.astimezone(LONDON).date()
    if start_date < horizon_start:
        return horizon_start, end_date, True
    return start_date, end_date, False


def iter_date_chunks(
    start_date: datetime.date, end_date: datetime.date, chunk_days: int
) -> "list[tuple[datetime.date, datetime.date]]":
    """Split [start_date, end_date] into inclusive windows of at most chunk_days."""
    chunk_days = max(1, chunk_days)
    chunks: list[tuple[datetime.date, datetime.date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + datetime.timedelta(days=chunk_days - 1), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + datetime.timedelta(days=1)
    return chunks


def collect_once(cfg: Config, writer: RemoteWriter) -> None:
    STATS.last_run_unixtime = time.time()

    state = load_meter_state(cfg.state_file, cfg.meter)
    hwm = state.last_pushed_hour
    now_london = datetime.datetime.now(LONDON)

    start_date, end_date, gap = compute_fetch_window(now_london, hwm, cfg.backfill_days)
    horizon_start = (
        now_london - datetime.timedelta(days=HOURLY_AVAILABILITY_DAYS - 1)
    ).date()

    if hwm is None:
        log.info(
            "No state found; backfilling hourly data from %s (hourly is only "
            "available for the last %d days)",
            start_date, HOURLY_AVAILABILITY_DAYS,
        )
    else:
        log.info("Resuming after high-water-mark %s", hwm.isoformat())
        if gap:
            log.warning(
                "Last reading %s predates the %d-day hourly window; hours before "
                "%s have aged out of Thames Water and cannot be recovered at "
                "hourly resolution (unrecoverable gap).",
                hwm.isoformat(), HOURLY_AVAILABILITY_DAYS, start_date,
            )

    base_labels = {
        "meter": str(cfg.meter),
        "account": str(cfg.account_number),
        **cfg.extra_labels,
    }

    log.info("Authenticating to Thames Water for meter %s", cfg.meter)
    client = ThamesWater(
        email=cfg.email,
        password=cfg.password,
        account_number=cfg.account_number,
    )

    chunks = iter_date_chunks(start_date, end_date, cfg.chunk_days)
    total_pushed = 0

    for i, (chunk_start, chunk_end) in enumerate(chunks):
        if i > 0 and cfg.chunk_delay_seconds > 0:
            _STOP.wait(cfg.chunk_delay_seconds)

        usage = client.get_meter_usage(
            cfg.meter,
            datetime.datetime.combine(chunk_start, datetime.time.min),
            datetime.datetime.combine(chunk_end, datetime.time.min),
        )
        if usage.IsError or not usage.IsDataAvailable or not usage.Lines:
            # Common when the window predates Thames Water's hourly availability:
            # nothing to align, so just move on to the next window.
            log.info(
                "No hourly data for %s..%s (IsError=%s, IsDataAvailable=%s, lines=%d); skipping",
                chunk_start, chunk_end, usage.IsError, usage.IsDataAvailable, len(usage.Lines),
            )
            continue

        measurements = lines_to_measurements(chunk_start, usage.Lines)

        # Timestamps are anchored to chunk_start, so the returned lines MUST begin
        # at chunk_start. That holds for any window inside the hourly availability
        # horizon (the whole range exists) and for the current window (only the
        # not-yet-reported tail is missing). A window that reaches back *before*
        # the horizon and returns far fewer hours than its span is straddling the
        # edge of availability (or has a gap) and would be misaligned -> skip it
        # rather than write wrong-timestamped samples.
        within_horizon = chunk_start >= horizon_start
        expected_hours = ((chunk_end - chunk_start).days + 1) * 24
        if not within_horizon and len(measurements) < expected_hours - 3:
            log.warning(
                "Window %s..%s returned %d/%d hours; likely the start of hourly "
                "availability or a gap. Skipping to avoid misaligned timestamps.",
                chunk_start, chunk_end, len(measurements), expected_hours,
            )
            continue

        to_push = select_new_final_measurements(measurements, hwm)
        if not to_push:
            continue

        payload = build_write_payload(to_push, base_labels)

        log.info(
            "Pushing %d finalised hours (%s -> %s), meter reading %.0f L, to %s",
            len(to_push),
            to_push[0].hour_start.isoformat(),
            to_push[-1].hour_start.isoformat(),
            to_push[-1].total,
            cfg.remote_write_url,
        )
        writer.send(payload)

        # Advance state after each window so a mid-backfill failure resumes cleanly.
        hwm = to_push[-1].hour_start
        save_meter_state(cfg.state_file, cfg.meter, hwm)
        total_pushed += len(to_push)
        STATS.samples_pushed_total += len(to_push) * len(payload)

    if total_pushed == 0:
        log.info("No new finalised hours to push this cycle")
    else:
        log.info("Cycle complete: pushed %d new finalised hours", total_pushed)
    STATS.last_success_unixtime = time.time()


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
_STOP = threading.Event()


def _handle_signal(signum, _frame):
    log.info("Received signal %s; shutting down after current cycle", signum)
    _STOP.set()


def main() -> None:
    cfg = Config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    _start_health_server(cfg.health_port)

    writer = RemoteWriter(
        url=cfg.remote_write_url,
        headers=cfg.remote_write_headers() or None,
        auth=cfg.remote_write_auth(),
        timeout=30,
        retries=3,
        auto_convert_seconds_to_ms=False,  # we already emit millisecond timestamps
    )

    log.info(
        "Thames Water exporter started (poll every %ds, backfill %d days)",
        cfg.poll_interval,
        cfg.backfill_days,
    )

    while not _STOP.is_set():
        try:
            collect_once(cfg, writer)
            STATS.up = 1
        except Exception:  # noqa: BLE001 - keep the loop alive across transient failures
            STATS.up = 0
            STATS.push_errors_total += 1
            log.exception("Collection cycle failed; will retry next interval")

        _STOP.wait(cfg.poll_interval)

    log.info("Exporter stopped")


if __name__ == "__main__":
    main()
