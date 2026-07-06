import datetime
import json

from thameswaterapi import Tariff

from thameswater_exporter.state import (
    load_cached_tariff,
    load_meter_state,
    save_cached_tariff,
    save_meter_state,
)

CACHED_TARIFF = Tariff(
    clean_water_rate_per_m3=1.1,
    wastewater_rate_per_m3=2.2,
    water_fixed_per_year=110.0,
    wastewater_fixed_per_year=220.0,
)


def test_save_and_load_meter_state_roundtrip(tmp_path):
    state_file = tmp_path / "state.json"
    hour = datetime.datetime(2026, 6, 22, 3, 0, tzinfo=datetime.timezone.utc)

    save_meter_state(
        str(state_file),
        "311379681",
        hour,
        new_data_push_unixtime=1_700_000_000.0,
        reading_litres=12345.0,
    )
    loaded = load_meter_state(str(state_file), "311379681")

    assert loaded.last_pushed_hour == hour
    assert loaded.last_new_data_push_unixtime == 1_700_000_000.0
    assert loaded.last_pushed_reading_litres == 12345.0


def test_load_meter_state_missing_file_returns_empty(tmp_path):
    state = load_meter_state(str(tmp_path / "missing.json"), "311379681")
    assert state.last_pushed_hour is None


def test_save_meter_state_overwrites_existing_meter(tmp_path):
    state_file = tmp_path / "state.json"
    first = datetime.datetime(2026, 6, 20, 10, 0, tzinfo=datetime.timezone.utc)
    second = datetime.datetime(2026, 6, 22, 3, 0, tzinfo=datetime.timezone.utc)

    save_meter_state(str(state_file), "311379681", first)
    save_meter_state(str(state_file), "311379681", second)

    data = json.loads(state_file.read_text())
    assert data["meters"]["311379681"]["last_pushed_hour"] == second.isoformat()


def test_save_and_load_cached_tariff_roundtrip(tmp_path):
    state_file = tmp_path / "state.json"
    save_cached_tariff(str(state_file), CACHED_TARIFF)
    loaded = load_cached_tariff(str(state_file))
    assert loaded == CACHED_TARIFF


def test_save_cached_tariff_preserves_meter_state(tmp_path):
    state_file = tmp_path / "state.json"
    hour = datetime.datetime(2026, 6, 22, 3, 0, tzinfo=datetime.timezone.utc)
    save_meter_state(str(state_file), "311379681", hour)
    save_cached_tariff(str(state_file), CACHED_TARIFF)

    data = json.loads(state_file.read_text())
    assert data["meters"]["311379681"]["last_pushed_hour"] == hour.isoformat()
    assert load_cached_tariff(str(state_file)) == CACHED_TARIFF


def test_load_cached_tariff_missing_returns_none(tmp_path):
    assert load_cached_tariff(str(tmp_path / "missing.json")) is None
