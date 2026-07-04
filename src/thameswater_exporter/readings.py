"""Adaptor between thameswaterapi and exporter-specific reading metadata."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from thameswaterapi import Line, meter_usage_lines_to_timeseries


@dataclass
class Measurement:
    hour_start: datetime.datetime
    usage: int
    total: int
    is_estimated: bool = False
    serial: str = ""


def lines_to_measurements(start: datetime.date, lines: list[Line]) -> list[Measurement]:
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
