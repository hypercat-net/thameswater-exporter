from __future__ import annotations

import datetime

from thameswater_exporter.constants import READING_METRIC, USAGE_METRIC
from thameswater_exporter.readings import Measurement


def build_write_payload(
    measurements: list[Measurement],
    base_labels: dict[str, str],
) -> list[dict]:
    timestamps = [
        int(m.hour_start.astimezone(datetime.timezone.utc).timestamp() * 1000)
        for m in measurements
    ]
    serial = measurements[-1].serial if measurements else ""
    labels = {**base_labels}
    if serial:
        labels["serial"] = serial

    return [
        {
            "metric": {"__name__": READING_METRIC, **labels},
            "values": [float(m.total) for m in measurements],
            "timestamps": list(timestamps),
        },
        {
            "metric": {"__name__": USAGE_METRIC, **labels},
            "values": [float(m.usage) for m in measurements],
            "timestamps": list(timestamps),
        },
    ]
