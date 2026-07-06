import datetime

from thameswaterapi import Account, Tariff

from thameswater_exporter.health import (
    STATS,
    format_gbp,
    format_reading_litres,
    format_unixtime,
    render_self_metrics,
    render_status_page,
    update_data_metrics,
    update_snapshot_metrics,
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


def test_format_gbp_unknown_for_zero():
    assert format_gbp(0) == "unknown"


def test_format_gbp_includes_currency_and_suffix():
    assert format_gbp(3.25, suffix="/day") == "GBP 3.2500/day"


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
    update_snapshot_metrics(
        tariff=Tariff(
            clean_water_rate_per_m3=1.0,
            wastewater_rate_per_m3=2.0,
            water_fixed_per_year=365.0,
            wastewater_fixed_per_year=730.0,
        ),
        account=Account(
            contractAccountNumber="900024395406",
            currentBalance=12.34,
            paymentDueAmount=56.78,
        ),
    )
    STATS.samples_pushed_total = 42
    STATS.push_errors_total = 1

    page = render_status_page(now=FIXED_NOW)
    assert "Status: OK" in page
    assert "Last collection cycle:     2026-07-05 11:58:00 UTC (2 minutes ago)" in page
    assert "Last collection attempt:   2026-07-05 11:59:00 UTC (1 minute ago)" in page
    assert "Last new data push:        2026-07-05 10:00:00 UTC (2 hours ago)" in page
    assert "Newest reading hour:       2026-07-04 22:00:00 UTC (14 hours ago)" in page
    assert "Last published reading:    1,046 L (1.046 m³)" in page
    assert "Tariff volumetric rate:    GBP 3.0000/m³" in page
    assert "Tariff clean water:        GBP 1.0000/m³" in page
    assert "Tariff wastewater:         GBP 2.0000/m³" in page
    assert "Water standing charge:     GBP 1.0000/day" in page
    assert "Wastewater standing:       GBP 2.0000/day" in page
    assert "Account current balance:   GBP 12.3400" in page
    assert "Account payment due:       GBP 56.7800" in page
    assert "Samples pushed (since restart): 42" in page
    assert "Push errors (since restart):    1" in page
    assert "Prometheus metrics: /metrics" in page
