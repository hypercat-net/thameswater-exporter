import datetime
import json

from thameswater_exporter.state import load_meter_state, save_meter_state


def test_save_and_load_meter_state_roundtrip(tmp_path):
    state_file = tmp_path / "state.json"
    hour = datetime.datetime(2026, 6, 22, 3, 0, tzinfo=datetime.timezone.utc)

    save_meter_state(str(state_file), "311379681", hour)
    loaded = load_meter_state(str(state_file), "311379681")

    assert loaded.last_pushed_hour == hour


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
