from thameswaterapi import Tariff

from thameswater_exporter.tariff import (
    hourly_volumetric_cost_gbp,
    tariff_snapshot_values,
    volumetric_rate_per_m3,
    water_standing_charge_per_day,
)


def test_volumetric_rate_per_m3():
    tariff = Tariff(1.25, 2.75, 100.0, 200.0)
    assert volumetric_rate_per_m3(tariff) == 4.0


def test_standing_charges_per_day():
    tariff = Tariff(0.0, 0.0, 365.0, 730.0)
    assert water_standing_charge_per_day(tariff) == 1.0
    assert hourly_volumetric_cost_gbp(500, Tariff(2.0, 2.0, 0.0, 0.0)) == 2.0


def test_tariff_snapshot_values_count():
    tariff = Tariff(1.0, 2.0, 365.0, 730.0)
    assert len(tariff_snapshot_values(tariff)) == 4
