import zoneinfo

LONDON = zoneinfo.ZoneInfo("Europe/London")

# Thames Water only serves *hourly* readings for roughly the last 7 days.
HOURLY_AVAILABILITY_DAYS = 7

READING_METRIC = "thameswater_meter_reading_litres_total"
USAGE_METRIC = "thameswater_hourly_usage_litres"
