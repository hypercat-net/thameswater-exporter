from thameswaterapi import Account, Tariff

from thameswater_exporter.constants import (
    ACCOUNT_CURRENT_BALANCE_METRIC,
    HOURLY_VOLUMETRIC_COST_METRIC,
    TARIFF_CLEAN_WATER_RATE_METRIC,
    TARIFF_STANDING_CHARGE_WASTEWATER_METRIC,
    TARIFF_STANDING_CHARGE_WATER_METRIC,
    TARIFF_WASTEWATER_RATE_METRIC,
)
from thameswater_exporter.remote_write import build_snapshot_payload, build_write_payload
from thameswater_exporter.tariff import hourly_volumetric_cost_gbp, wastewater_standing_charge_per_day


def _measurement(hour: int, usage: int, total: int):
    import datetime

    from thameswater_exporter.readings import Measurement

    return Measurement(
        hour_start=datetime.datetime(
            2026, 6, 22, hour, 0, tzinfo=datetime.timezone.utc
        ),
        usage=usage,
        total=total,
        is_estimated=False,
        serial="SN9",
    )


TARIFF = Tariff(
    clean_water_rate_per_m3=1.0,
    wastewater_rate_per_m3=2.0,
    water_fixed_per_year=365.0,
    wastewater_fixed_per_year=730.0,
)
ACCOUNT = Account(
    contractAccountNumber="900024395406",
    currentBalance=12.34,
    paymentDueAmount=56.78,
)
LABELS = {"meter": "311379681", "account": "900024395406"}


def test_hourly_volumetric_cost_gbp():
    assert hourly_volumetric_cost_gbp(1000, TARIFF) == 3.0


def test_build_write_payload_includes_cost_when_tariff_present():
    measurements = [_measurement(0, 100, 1100), _measurement(1, 200, 1300)]
    payload = build_write_payload(measurements, LABELS, tariff=TARIFF)
    assert len(payload) == 3
    cost = next(s for s in payload if s["metric"]["__name__"] == HOURLY_VOLUMETRIC_COST_METRIC)
    assert cost["values"] == [0.3, 0.6]


def test_build_write_payload_omits_cost_without_tariff():
    measurements = [_measurement(0, 100, 1100)]
    payload = build_write_payload(measurements, LABELS)
    assert len(payload) == 2
    assert all(
        s["metric"]["__name__"] != HOURLY_VOLUMETRIC_COST_METRIC for s in payload
    )


def test_build_snapshot_payload_includes_tariff_and_account():
    payload = build_snapshot_payload(LABELS, 1_700_000_000_000, tariff=TARIFF, account=ACCOUNT)
    names = {s["metric"]["__name__"] for s in payload}
    assert names == {
        TARIFF_CLEAN_WATER_RATE_METRIC,
        TARIFF_WASTEWATER_RATE_METRIC,
        TARIFF_STANDING_CHARGE_WATER_METRIC,
        TARIFF_STANDING_CHARGE_WASTEWATER_METRIC,
        ACCOUNT_CURRENT_BALANCE_METRIC,
    }
    standing = next(
        s
        for s in payload
        if s["metric"]["__name__"] == TARIFF_STANDING_CHARGE_WASTEWATER_METRIC
    )
    assert standing["values"] == [wastewater_standing_charge_per_day(TARIFF)]
