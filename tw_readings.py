"""Exporter-specific reading types and conversion from thameswaterapi.

The PyPI package ``thameswaterapi`` (https://github.com/jelmer/thameswaterapi)
handles Thames Water authentication and API calls. This module adds the fields
the exporter needs that are not on ``HourlyMeasurement``: ``is_estimated`` and
``serial``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from thameswaterapi import Line, meter_usage_lines_to_timeseries


@dataclass
class Measurement:
    hour_start: datetime.datetime
    usage: int  # litres used during the hour (Usage)
    total: int  # cumulative meter dial in litres at end of hour (Read)
    is_estimated: bool = False
    serial: str = ""


def lines_to_measurements(start: datetime.date, lines: list[Line]) -> list[Measurement]:
    """Convert API lines to exporter measurements with estimation + serial metadata."""
    hourly = meter_usage_lines_to_timeseries(start, lines)
    return [
        Measurement(
            hour_start=h.hour_start,
            usage=h.usage,
            total=h.total,
            is_estimated=bool(line.IsEstimated),
            serial=line.MeterSerialNumberHis,
        )
        for h, line in zip(hourly, lines)
    ]
