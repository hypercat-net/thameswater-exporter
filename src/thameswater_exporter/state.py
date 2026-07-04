from __future__ import annotations

import datetime
import json
import logging
import os

log = logging.getLogger(__name__)


class MeterState:
    def __init__(self, last_pushed_hour: datetime.datetime | None) -> None:
        self.last_pushed_hour = last_pushed_hour


def load_meter_state(state_file: str, meter: str) -> MeterState:
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        return MeterState(None)
    except (OSError, ValueError) as exc:
        log.warning("Could not read state file %s: %s", state_file, exc)
        return MeterState(None)

    iso = state.get("meters", {}).get(str(meter), {}).get("last_pushed_hour")
    return MeterState(
        datetime.datetime.fromisoformat(iso) if iso else None,
    )


def save_meter_state(
    state_file: str,
    meter: str,
    hour_start: datetime.datetime,
) -> None:
    state: dict = {"meters": {}}
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (FileNotFoundError, ValueError):
        pass

    state.setdefault("meters", {})[str(meter)] = {
        "last_pushed_hour": hour_start.astimezone(datetime.timezone.utc).isoformat(),
    }

    parent = os.path.dirname(state_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{state_file}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, state_file)
