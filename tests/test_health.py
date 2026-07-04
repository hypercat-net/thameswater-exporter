import datetime

from thameswater_exporter.health import STATS, render_self_metrics, update_data_metrics


def test_render_self_metrics_includes_data_freshness_metrics():
    hour = datetime.datetime(2026, 6, 22, 2, 0, tzinfo=datetime.timezone.utc)
    update_data_metrics(hour, 1_700_000_000.0)
    body = render_self_metrics()
    assert "thameswater_exporter_last_pushed_hour_timestamp_seconds" in body
    assert "thameswater_exporter_last_new_data_push_timestamp_seconds" in body
    assert (
        f"thameswater_exporter_last_pushed_hour_timestamp_seconds {hour.timestamp()}"
        in body
    )
    assert "thameswater_exporter_last_new_data_push_timestamp_seconds 1700000000" in body


def test_update_data_metrics_leaves_absent_values_unchanged():
    STATS.last_new_data_push_unixtime = 99.0
    update_data_metrics(
        datetime.datetime(2026, 6, 22, 2, 0, tzinfo=datetime.timezone.utc),
    )
    assert STATS.last_new_data_push_unixtime == 99.0
