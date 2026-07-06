from __future__ import annotations

import datetime

from thameswaterapi import Account, Tariff

from thameswater_exporter.constants import HOURLY_VOLUMETRIC_COST_METRIC, READING_METRIC, USAGE_METRIC
from thameswater_exporter.readings import Measurement
from thameswater_exporter.tariff import (
    account_snapshot_values,
    hourly_volumetric_cost_gbp,
    tariff_snapshot_values,
)


def _gauge_series(
    name: str,
    value: float,
    labels: dict[str, str],
    timestamp_ms: int,
) -> dict:
    return {
        "metric": {"__name__": name, **labels},
        "values": [value],
        "timestamps": [timestamp_ms],
    }


def build_write_payload(
    measurements: list[Measurement],
    base_labels: dict[str, str],
    *,
    tariff: Tariff | None = None,
) -> list[dict]:
    timestamps = [
        int(m.hour_start.astimezone(datetime.timezone.utc).timestamp() * 1000)
        for m in measurements
    ]
    serial = measurements[-1].serial if measurements else ""
    labels = {**base_labels}
    if serial:
        labels["serial"] = serial

    payload = [
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
    if tariff is not None:
        payload.append(
            {
                "metric": {"__name__": HOURLY_VOLUMETRIC_COST_METRIC, **labels},
                "values": [hourly_volumetric_cost_gbp(m.usage, tariff) for m in measurements],
                "timestamps": list(timestamps),
            }
        )
    return payload


def build_snapshot_payload(
    base_labels: dict[str, str],
    timestamp_ms: int,
    *,
    tariff: Tariff | None = None,
    account: Account | None = None,
) -> list[dict]:
    payload: list[dict] = []
    if tariff is not None:
        for name, value in tariff_snapshot_values(tariff):
            payload.append(_gauge_series(name, value, base_labels, timestamp_ms))
    if account is not None:
        for name, value in account_snapshot_values(account):
            payload.append(_gauge_series(name, value, base_labels, timestamp_ms))
    return payload
