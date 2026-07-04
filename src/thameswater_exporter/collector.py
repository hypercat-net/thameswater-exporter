from __future__ import annotations

import datetime
import logging
import threading
import time

from prometheus_remote_writer import RemoteWriter
from thameswaterapi import ThamesWater

from thameswater_exporter.config import Config
from thameswater_exporter.constants import HOURLY_AVAILABILITY_DAYS, LONDON
from thameswater_exporter.health import STATS, update_data_metrics
from thameswater_exporter.readings import Measurement, lines_to_measurements
from thameswater_exporter.remote_write import build_write_payload
from thameswater_exporter.state import load_meter_state, save_meter_state

log = logging.getLogger(__name__)


def select_new_final_measurements(
    measurements: list[Measurement],
    high_water_mark: datetime.datetime | None,
) -> list[Measurement]:
    ordered = sorted(measurements, key=lambda m: m.hour_start)
    selected: list[Measurement] = []
    for m in ordered:
        if high_water_mark is not None and m.hour_start <= high_water_mark:
            continue
        if m.is_estimated:
            break
        selected.append(m)
    return selected


def compute_fetch_window(
    now_london: datetime.datetime,
    hwm: datetime.datetime | None,
    backfill_days: int,
) -> tuple[datetime.date, datetime.date, bool]:
    end_date = now_london.date()
    horizon_start = (
        now_london - datetime.timedelta(days=HOURLY_AVAILABILITY_DAYS - 1)
    ).date()

    if hwm is None:
        requested = (now_london - datetime.timedelta(days=backfill_days - 1)).date()
        return max(requested, horizon_start), end_date, False

    start_date = hwm.astimezone(LONDON).date()
    if start_date < horizon_start:
        return horizon_start, end_date, True
    return start_date, end_date, False


def iter_date_chunks(
    start_date: datetime.date, end_date: datetime.date, chunk_days: int
) -> list[tuple[datetime.date, datetime.date]]:
    chunk_days = max(1, chunk_days)
    chunks: list[tuple[datetime.date, datetime.date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + datetime.timedelta(days=chunk_days - 1), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + datetime.timedelta(days=1)
    return chunks


def collect_once(
    cfg: Config,
    writer: RemoteWriter,
    stop_event: threading.Event,
) -> None:
    STATS.last_run_unixtime = time.time()

    state = load_meter_state(cfg.state_file, cfg.meter)
    hwm = state.last_pushed_hour
    update_data_metrics(hwm, state.last_new_data_push_unixtime)
    now_london = datetime.datetime.now(LONDON)

    start_date, end_date, gap = compute_fetch_window(now_london, hwm, cfg.backfill_days)
    horizon_start = (
        now_london - datetime.timedelta(days=HOURLY_AVAILABILITY_DAYS - 1)
    ).date()

    if hwm is None:
        log.info(
            "No state found; backfilling hourly data from %s (hourly is only "
            "available for the last %d days)",
            start_date,
            HOURLY_AVAILABILITY_DAYS,
        )
    else:
        log.info("Resuming after high-water-mark %s", hwm.isoformat())
        if gap:
            log.warning(
                "Last reading %s predates the %d-day hourly window; hours before "
                "%s have aged out of Thames Water and cannot be recovered at "
                "hourly resolution (unrecoverable gap).",
                hwm.isoformat(),
                HOURLY_AVAILABILITY_DAYS,
                start_date,
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
            stop_event.wait(cfg.chunk_delay_seconds)

        usage = client.get_meter_usage(
            cfg.meter,
            datetime.datetime.combine(chunk_start, datetime.time.min),
            datetime.datetime.combine(chunk_end, datetime.time.min),
        )
        if usage.IsError or not usage.IsDataAvailable or not usage.Lines:
            log.info(
                "No hourly data for %s..%s (IsError=%s, IsDataAvailable=%s, lines=%d); skipping",
                chunk_start,
                chunk_end,
                usage.IsError,
                usage.IsDataAvailable,
                len(usage.Lines),
            )
            continue

        measurements = lines_to_measurements(chunk_start, usage.Lines)

        within_horizon = chunk_start >= horizon_start
        expected_hours = ((chunk_end - chunk_start).days + 1) * 24
        if not within_horizon and len(measurements) < expected_hours - 3:
            log.warning(
                "Window %s..%s returned %d/%d hours; likely the start of hourly "
                "availability or a gap. Skipping to avoid misaligned timestamps.",
                chunk_start,
                chunk_end,
                len(measurements),
                expected_hours,
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

        hwm = to_push[-1].hour_start
        push_unixtime = time.time()
        save_meter_state(
            cfg.state_file,
            cfg.meter,
            hwm,
            new_data_push_unixtime=push_unixtime,
        )
        update_data_metrics(hwm, push_unixtime)
        total_pushed += len(to_push)
        STATS.samples_pushed_total += len(to_push) * len(payload)

    if total_pushed == 0:
        log.info("No new finalised hours to push this cycle")
    else:
        log.info("Cycle complete: pushed %d new finalised hours", total_pushed)
    STATS.last_success_unixtime = time.time()
