import datetime
import zoneinfo

from thameswaterapi import Line
from thameswater_exporter.collector import (
    compute_fetch_window,
    iter_date_chunks,
    select_new_final_measurements,
)
from thameswater_exporter.constants import HOURLY_AVAILABILITY_DAYS
from thameswater_exporter.readings import Measurement, lines_to_measurements
from thameswater_exporter.remote_write import build_write_payload

LONDON = zoneinfo.ZoneInfo("Europe/London")


def _m(hour, usage, total, estimated=False):
    return Measurement(
        hour_start=datetime.datetime(2025, 2, 11, hour, tzinfo=LONDON),
        usage=usage,
        total=total,
        is_estimated=estimated,
        serial="ABC123",
    )


def test_selection_stops_at_first_estimated_hour():
    measurements = [
        _m(0, 10, 1000),
        _m(1, 20, 1020),
        _m(2, 30, 1050, estimated=True),
        _m(3, 40, 1090),
    ]
    selected = select_new_final_measurements(measurements, high_water_mark=None)
    assert [m.hour_start.hour for m in selected] == [0, 1]


def test_selection_skips_already_pushed_hours():
    measurements = [_m(0, 10, 1000), _m(1, 20, 1020), _m(2, 30, 1050)]
    hwm = datetime.datetime(2025, 2, 11, 0, tzinfo=LONDON)
    selected = select_new_final_measurements(measurements, high_water_mark=hwm)
    assert [m.hour_start.hour for m in selected] == [1, 2]


def test_write_payload_uses_meter_read_from_api():
    measurements = [_m(0, 10, 1000), _m(1, 20, 1020), _m(2, 30, 1050)]
    payload = build_write_payload(measurements, {"meter": "M1", "account": "x"})
    reading = next(
        s for s in payload if s["metric"]["__name__"] == "thameswater_meter_reading_litres_total"
    )
    assert reading["values"] == [1000.0, 1020.0, 1050.0]
    assert all(b >= a for a, b in zip(reading["values"], reading["values"][1:]))


def test_lines_to_measurements_carries_estimated_and_serial():
    lines = [
        Line(Label="0:00", Usage=10, Read=1000, IsEstimated=True, MeterSerialNumberHis="SN1"),
        Line(Label="1:00", Usage=5, Read=1005, IsEstimated=False, MeterSerialNumberHis="SN1"),
    ]
    out = lines_to_measurements(datetime.date(2025, 2, 11), lines)
    assert out[0].is_estimated is True
    assert out[1].is_estimated is False
    assert out[0].serial == "SN1"


def test_conversion_emits_one_hourly_timestamp_per_line():
    lines = [
        Line(Label=f"{h}:00", Usage=h, Read=100 + h, IsEstimated=False, MeterSerialNumberHis="SN")
        for h in range(6)
    ]
    out = lines_to_measurements(datetime.date(2025, 2, 11), lines)
    assert len(out) == 6
    hours = [m.hour_start for m in out]
    assert hours == sorted(hours)
    assert len(set(hours)) == 6
    assert (hours[1] - hours[0]) == datetime.timedelta(hours=1)


def test_iter_date_chunks_covers_range_without_overlap():
    chunks = iter_date_chunks(datetime.date(2025, 1, 1), datetime.date(2025, 1, 20), 7)
    assert chunks == [
        (datetime.date(2025, 1, 1), datetime.date(2025, 1, 7)),
        (datetime.date(2025, 1, 8), datetime.date(2025, 1, 14)),
        (datetime.date(2025, 1, 15), datetime.date(2025, 1, 20)),
    ]
    for (_, end), (nxt_start, _) in zip(chunks, chunks[1:]):
        assert nxt_start == end + datetime.timedelta(days=1)


def test_iter_date_chunks_single_day():
    d = datetime.date(2025, 1, 1)
    assert iter_date_chunks(d, d, 7) == [(d, d)]


NOW = datetime.datetime(2025, 6, 28, 12, 0, tzinfo=LONDON)


def test_backfill_is_clamped_to_hourly_horizon():
    start, end, gap = compute_fetch_window(NOW, hwm=None, backfill_days=90)
    assert end == NOW.date()
    assert start == (NOW - datetime.timedelta(days=HOURLY_AVAILABILITY_DAYS - 1)).date()
    assert gap is False


def test_short_backfill_is_respected():
    start, _, gap = compute_fetch_window(NOW, hwm=None, backfill_days=2)
    assert start == (NOW - datetime.timedelta(days=1)).date()
    assert gap is False


def test_resume_within_window_starts_at_high_water_mark():
    hwm = datetime.datetime(2025, 6, 26, 9, tzinfo=LONDON)
    start, _, gap = compute_fetch_window(NOW, hwm=hwm, backfill_days=7)
    assert start == datetime.date(2025, 6, 26)
    assert gap is False


def test_resume_after_long_outage_flags_unrecoverable_gap():
    hwm = datetime.datetime(2025, 5, 1, 9, tzinfo=LONDON)
    start, _, gap = compute_fetch_window(NOW, hwm=hwm, backfill_days=7)
    assert start == (NOW - datetime.timedelta(days=HOURLY_AVAILABILITY_DAYS - 1)).date()
    assert gap is True
