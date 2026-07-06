"""Tariff and account snapshot helpers."""

from __future__ import annotations

from thameswaterapi import Account, Tariff

from thameswater_exporter.constants import (
    ACCOUNT_CURRENT_BALANCE_METRIC,
    TARIFF_CLEAN_WATER_RATE_METRIC,
    TARIFF_STANDING_CHARGE_WASTEWATER_METRIC,
    TARIFF_STANDING_CHARGE_WATER_METRIC,
    TARIFF_WASTEWATER_RATE_METRIC,
)


def volumetric_rate_per_m3(tariff: Tariff) -> float:
    return tariff.clean_water_rate_per_m3 + tariff.wastewater_rate_per_m3


def hourly_volumetric_cost_gbp(usage_litres: int, tariff: Tariff) -> float:
    return round((usage_litres / 1000) * volumetric_rate_per_m3(tariff), 6)


def water_standing_charge_per_day(tariff: Tariff) -> float:
    return round(tariff.water_fixed_per_year / 365, 4)


def wastewater_standing_charge_per_day(tariff: Tariff) -> float:
    return round(tariff.wastewater_fixed_per_year / 365, 4)


def tariff_snapshot_values(tariff: Tariff) -> list[tuple[str, float]]:
    return [
        (TARIFF_CLEAN_WATER_RATE_METRIC, tariff.clean_water_rate_per_m3),
        (TARIFF_WASTEWATER_RATE_METRIC, tariff.wastewater_rate_per_m3),
        (TARIFF_STANDING_CHARGE_WATER_METRIC, water_standing_charge_per_day(tariff)),
        (
            TARIFF_STANDING_CHARGE_WASTEWATER_METRIC,
            wastewater_standing_charge_per_day(tariff),
        ),
    ]


def account_snapshot_values(account: Account) -> list[tuple[str, float]]:
    return [
        (ACCOUNT_CURRENT_BALANCE_METRIC, account.currentBalance),
    ]
