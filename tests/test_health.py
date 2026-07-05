import datetime

from thameswater_exporter.health import (
    STATS,
    format_reading_litres,
    format_unixtime,
    render_self_metrics,
    render_status_page,
    update_data_metrics,
)

FIXED_NOW = datetime.datetime(2026, 7, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)


def test_render_self_metrics_includes_data_freshness_metrics():
    hour = datetime.datetime(2026, 6, 22, 2, 0, tzinfo=datetime.timezone.utc)
    update_data_metrics(hour, 1_700_000_000.0, 12_345.0)
    body = render_self_metrics()
    assert "thameswater_exporter_last_pushed_hour_timestamp_seconds" in body
    assert "thameswater_exporter_last_new_data_push_timestamp_seconds" in body
    assert "thameswater_exporter_last_pushed_reading_litres" in body
    assert (
        f"thameswater_exporter_last_pushed_hour_timestamp_seconds {hour.timestamp()}"
        in body
    )
    assert "thameswater_exporter_last_new_data_push_timestamp_seconds 1700000000" in body
    assert "thameswater_exporter_last_pushed_reading_litres 12345" in body


def test_update_data_metrics_leaves_absent_values_unchanged():
    STATS.last_new_data_push_unixtime = 99.0
    update_data_metrics(
        datetime.datetime(2026, 6, 22, 2, 0, tzinfo=datetime.timezone.utc),
    )
    assert STATS.last_new_data_push_unixtime == 99.0


def test_format_reading_litres_unknown_for_zero():
    assert format_reading_litres(0) == "unknown"


def test_format_reading_litres_includes_litres_and_cubic_metres():
    assert format_reading_litres(1046) == "1,046 L (1.046 m³)"


def test_format_unixtime_never_for_zero():
    assert format_unixtime(0) == "never"


def test_format_unixtime_includes_datetime_and_ago():
    ts = datetime.datetime(2026, 7, 5, 10, 30, 0, tzinfo=datetime.timezone.utc).timestamp()
    text = format_unixtime(ts, now=FIXED_NOW)
    assert text == "2026-07-05 10:30:00 UTC (1 hour 30 minutes ago)"


def test_render_status_page_is_human_readable():
    STATS.up = 1
    STATS.last_success_unixtime = FIXED_NOW.timestamp() - 120
    STATS.last_run_unixtime = FIXED_NOW.timestamp() - 60
    STATS.last_new_data_push_unixtime = FIXED_NOW.timestamp() - 7200
    STATS.last_pushed_hour_unixtime = datetime.datetime(
        2026, 7, 4, 22, 0, tzinfo=datetime.timezone.utc
    ).timestamp()
    STATS.last_pushed_reading_litres = 1046
    STATS.samples_pushed_total = 42
    STATS.push_errors_total = 1

    page = render_status_page(now=FIXED_NOW)
    assert "Status: OK" in page
    assert "Last collection cycle:     2026-07-05 11:58:00 UTC (2 minutes ago)" in page
    assert "Last collection attempt:   2026-07-05 11:59:00 UTC (1 minute ago)" in page
    assert "Last new data push:        2026-07-05 10:00:00 UTC (2 hours ago)" in page
    assert "Newest reading hour:       2026-07-04 22:00:00 UTC (14 hours ago)" in page
    assert "Last published reading:    1,046 L (1.046 m³)" in page
    assert "Samples pushed (since restart): 42" in page
    assert "Push errors (since restart):    1" in page
    assert "Prometheus metrics: /metrics" in page
