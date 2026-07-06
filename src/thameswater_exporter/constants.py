import zoneinfo

LONDON = zoneinfo.ZoneInfo("Europe/London")

# Thames Water only serves *hourly* readings for roughly the last 7 days.
HOURLY_AVAILABILITY_DAYS = 7

READING_METRIC = "thameswater_meter_reading_litres_total"
USAGE_METRIC = "thameswater_hourly_usage_litres"
HOURLY_VOLUMETRIC_COST_METRIC = "thameswater_hourly_volumetric_cost_gbp"

TARIFF_CLEAN_WATER_RATE_METRIC = "thameswater_tariff_clean_water_rate_gbp_per_m3"
TARIFF_WASTEWATER_RATE_METRIC = "thameswater_tariff_wastewater_rate_gbp_per_m3"
TARIFF_STANDING_CHARGE_WATER_METRIC = "thameswater_tariff_water_standing_charge_gbp_per_day"
TARIFF_STANDING_CHARGE_WASTEWATER_METRIC = (
    "thameswater_tariff_wastewater_standing_charge_gbp_per_day"
)

ACCOUNT_CURRENT_BALANCE_METRIC = "thameswater_account_current_balance_gbp"
ACCOUNT_PAYMENT_DUE_METRIC = "thameswater_account_payment_due_gbp"
