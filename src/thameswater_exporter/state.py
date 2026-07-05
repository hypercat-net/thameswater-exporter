from __future__ import annotations

import datetime
import json
import logging
import os

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


def load_meter_state(state_file: str, meter: str) -> MeterState:
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        return MeterState(None)
    except (OSError, ValueError) as exc:
        log.warning("Could not read state file %s: %s", state_file, exc)
        return MeterState(None)

    meter_state = state.get("meters", {}).get(str(meter), {})
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
    state: dict = {"meters": {}}
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        log.debug("State file %s does not exist yet; creating a new one", state_file)
    except ValueError as exc:
        log.warning("State file %s is invalid JSON, resetting state: %s", state_file, exc)

    entry: dict = {
        "last_pushed_hour": hour_start.astimezone(datetime.timezone.utc).isoformat(),
    }
    if new_data_push_unixtime is not None:
        entry["last_new_data_push_unixtime"] = new_data_push_unixtime
    if reading_litres is not None:
        entry["last_pushed_reading_litres"] = reading_litres
    state.setdefault("meters", {})[str(meter)] = entry

    parent = os.path.dirname(state_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{state_file}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, state_file)
