import os
import datetime

import pytest
from dotenv import load_dotenv
from thameswaterapi import ThamesWater

from thameswater_exporter.readings import lines_to_measurements

load_dotenv()

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(k) for k in ("EMAIL", "PASSWORD", "ACCOUNT_NUMBER", "METER")),
    reason="Thames Water credentials not configured in .env",
)


def test_hourly_reading_retrieval():
    thames_water = ThamesWater(
        email=os.environ["EMAIL"],
        password=os.environ["PASSWORD"],
        account_number=int(os.environ["ACCOUNT_NUMBER"]),
    )

    start = datetime.date(2025, 2, 11)
    end = datetime.date(2025, 2, 16)
    meter = int(os.environ["METER"])

    meter_usage = thames_water.get_meter_usage(
        meter,
        datetime.datetime.combine(start, datetime.time.min),
        datetime.datetime.combine(end, datetime.time.min),
    )
    readings = lines_to_measurements(start, meter_usage.Lines)

    assert len(readings) > 0
