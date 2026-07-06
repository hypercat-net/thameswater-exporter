from __future__ import annotations

import datetime
import json
import logging
import os

from thameswaterapi import Tariff

log = logging.getLogger(__name__)


class MeterState:
    def __init__(
        self,
        last_pushed_hour: datetime.datetime | None,
        last_new_data_push_unixtime: float | None = None,
        last_pushed_reading_litres: float | None = None,
    ) -> None:
        self.last_pushed_hour = last_pushed_hour
        self.last_new_data_push_unixtime = last_new_data_push_unixtime
        self.last_pushed_reading_litres = last_pushed_reading_litres


def _load_state_file(state_file: str) -> dict:
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Could not read state file %s: %s", state_file, exc)
        return {}


def _write_state_file(state_file: str, state: dict) -> None:
    parent = os.path.dirname(state_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{state_file}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, state_file)


def load_meter_state(state_file: str, meter: str) -> MeterState:
    meter_state = _load_state_file(state_file).get("meters", {}).get(str(meter), {})
    iso = meter_state.get("last_pushed_hour")
    push_unixtime = meter_state.get("last_new_data_push_unixtime")
    reading_litres = meter_state.get("last_pushed_reading_litres")
    return MeterState(
        datetime.datetime.fromisoformat(iso) if iso else None,
        float(push_unixtime) if push_unixtime is not None else None,
        float(reading_litres) if reading_litres is not None else None,
    )


def save_meter_state(
    state_file: str,
    meter: str,
    hour_start: datetime.datetime,
    *,
    new_data_push_unixtime: float | None = None,
    reading_litres: float | None = None,
) -> None:
    state = _load_state_file(state_file)
    if not state and not os.path.exists(state_file):
        log.debug("State file %s does not exist yet; creating a new one", state_file)

    entry: dict = {
        "last_pushed_hour": hour_start.astimezone(datetime.timezone.utc).isoformat(),
    }
    if new_data_push_unixtime is not None:
        entry["last_new_data_push_unixtime"] = new_data_push_unixtime
    if reading_litres is not None:
        entry["last_pushed_reading_litres"] = reading_litres
    state.setdefault("meters", {})[str(meter)] = entry
    _write_state_file(state_file, state)


def load_cached_tariff(state_file: str) -> Tariff | None:
    raw = _load_state_file(state_file).get("tariff")
    if not raw:
        return None
    try:
        return Tariff(
            clean_water_rate_per_m3=float(raw["clean_water_rate_per_m3"]),
            wastewater_rate_per_m3=float(raw["wastewater_rate_per_m3"]),
            water_fixed_per_year=float(raw["water_fixed_per_year"]),
            wastewater_fixed_per_year=float(raw["wastewater_fixed_per_year"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("Ignoring invalid cached tariff in %s: %s", state_file, exc)
        return None


def save_cached_tariff(state_file: str, tariff: Tariff) -> None:
    state = _load_state_file(state_file)
    state["tariff"] = {
        "clean_water_rate_per_m3": tariff.clean_water_rate_per_m3,
        "wastewater_rate_per_m3": tariff.wastewater_rate_per_m3,
        "water_fixed_per_year": tariff.water_fixed_per_year,
        "wastewater_fixed_per_year": tariff.wastewater_fixed_per_year,
        "cached_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _write_state_file(state_file, state)
