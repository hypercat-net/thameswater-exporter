import datetime
import json
import threading
from types import SimpleNamespace

import pytest
from thameswaterapi import Line, MeterUsage

from thameswater_exporter.collector import collect_once
from thameswater_exporter.constants import LONDON
from thameswater_exporter.health import STATS

FIXED_NOW = datetime.datetime(2026, 6, 28, 12, 0, tzinfo=LONDON)


class FrozenDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


def _freeze_now(monkeypatch) -> None:
    monkeypatch.setattr(
        "thameswater_exporter.collector.datetime.datetime",
        FrozenDateTime,
    )


def _meter_usage(lines: list[Line]) -> MeterUsage:
    return MeterUsage(
        IsError=False,
        IsDataAvailable=True,
        IsConsumptionAvailable=True,
        TargetUsage=0,
        AverageUsage=0,
        ActualUsage=0,
        MyUsage="NA",
        AverageUsagePerPerson=0,
        IsMO365Customer=False,
        IsMOPartialCustomer=False,
        IsMOCompleteCustomer=False,
        IsExtraMonthConsumptionMessage=False,
        Lines=lines,
    )


def _lines(n: int, *, estimated_from: int | None = None) -> list[Line]:
    lines = []
    read = 1000
    for h in range(n):
        usage = 10 + h
        read += usage
        lines.append(
            Line(
                Label=f"{h}:00",
                Usage=float(usage),
                Read=float(read),
                IsEstimated=estimated_from is not None and h >= estimated_from,
                MeterSerialNumberHis="SN9",
            )
        )
    return lines


def _cfg(state_file: str) -> SimpleNamespace:
    return SimpleNamespace(
        email="user@example.com",
        password="secret",
        account_number="900024395406",
        meter="311379681",
        state_file=state_file,
        backfill_days=7,
        chunk_days=7,
        chunk_delay_seconds=0,
        remote_write_url="http://mimir:9009/api/v1/push",
        extra_labels={},
    )


@pytest.fixture
def reset_stats():
    before = (
        STATS.last_success_unixtime,
        STATS.last_run_unixtime,
        STATS.last_pushed_hour_unixtime,
        STATS.last_new_data_push_unixtime,
        STATS.last_pushed_reading_litres,
        STATS.samples_pushed_total,
        STATS.push_errors_total,
        STATS.up,
    )
    yield
    (
        STATS.last_success_unixtime,
        STATS.last_run_unixtime,
        STATS.last_pushed_hour_unixtime,
        STATS.last_new_data_push_unixtime,
        STATS.last_pushed_reading_litres,
        STATS.samples_pushed_total,
        STATS.push_errors_total,
        STATS.up,
    ) = before


def test_collect_once_pushes_final_hours_and_persists_state(
    tmp_path, monkeypatch, reset_stats
):
    _freeze_now(monkeypatch)

    state_file = tmp_path / "state.json"
    cfg = _cfg(str(state_file))
    stop = threading.Event()
    pushed: list[dict] = []

    class FakeWriter:
        def send(self, payload):
            pushed.append(payload)

    # 5 hours; hour 4 is estimated -> push 4 finalised hours only.
    usage = _meter_usage(_lines(5, estimated_from=4))

    class FakeTW:
        def __init__(self, **kwargs):
            pass

        def get_meter_usage(self, meter, start, end, granularity="H"):
            return usage

    monkeypatch.setattr("thameswater_exporter.collector.ThamesWater", FakeTW)

    collect_once(cfg, FakeWriter(), stop)

    assert len(pushed) == 1
    reading = next(
        s for s in pushed[0] if s["metric"]["__name__"] == "thameswater_meter_reading_litres_total"
    )
    assert len(reading["values"]) == 4
    assert reading["values"] == [1010.0, 1021.0, 1033.0, 1046.0]

    saved = json.loads(state_file.read_text())
    last = saved["meters"]["311379681"]["last_pushed_hour"]
    assert datetime.datetime.fromisoformat(last) == datetime.datetime(
        2026, 6, 22, 2, 0, tzinfo=datetime.timezone.utc
    )
    assert STATS.last_pushed_hour_unixtime == datetime.datetime(
        2026, 6, 22, 2, 0, tzinfo=datetime.timezone.utc
    ).timestamp()
    assert STATS.last_new_data_push_unixtime > 0
    assert saved["meters"]["311379681"]["last_pushed_reading_litres"] == 1046.0
    assert STATS.last_pushed_reading_litres == 1046.0

    pushed.clear()
    collect_once(cfg, FakeWriter(), stop)
    assert pushed == []


def test_collect_once_resumes_after_high_water_mark(
    tmp_path, monkeypatch, reset_stats
):
    _freeze_now(monkeypatch)

    state_file = tmp_path / "state.json"
    hwm = datetime.datetime(2026, 6, 22, 2, 0, tzinfo=LONDON)
    state_file.write_text(
        json.dumps(
            {
                "meters": {
                    "311379681": {
                        "last_pushed_hour": hwm.astimezone(datetime.timezone.utc).isoformat(),
                    }
                }
            }
        )
    )

    cfg = _cfg(str(state_file))
    stop = threading.Event()
    pushed: list[dict] = []

    class FakeWriter:
        def send(self, payload):
            pushed.append(payload)

    usage = _meter_usage(_lines(5, estimated_from=4))

    class FakeTW:
        def __init__(self, **kwargs):
            pass

        def get_meter_usage(self, meter, start, end, granularity="H"):
            return usage

    monkeypatch.setattr("thameswater_exporter.collector.ThamesWater", FakeTW)

    collect_once(cfg, FakeWriter(), stop)

    reading = next(
        s for s in pushed[0] if s["metric"]["__name__"] == "thameswater_meter_reading_litres_total"
    )
    assert len(reading["values"]) == 1
    assert reading["values"] == [1046.0]


def test_collect_once_skips_empty_api_response(tmp_path, monkeypatch, reset_stats):
    _freeze_now(monkeypatch)

    state_file = tmp_path / "state.json"
    cfg = _cfg(str(state_file))
    stop = threading.Event()
    pushed: list[dict] = []

    class FakeWriter:
        def send(self, payload):
            pushed.append(payload)

    empty = _meter_usage([])
    empty.IsDataAvailable = False

    class FakeTW:
        def __init__(self, **kwargs):
            pass

        def get_meter_usage(self, meter, start, end, granularity="H"):
            return empty

    monkeypatch.setattr("thameswater_exporter.collector.ThamesWater", FakeTW)

    collect_once(cfg, FakeWriter(), stop)

    assert pushed == []
    assert not state_file.exists()
