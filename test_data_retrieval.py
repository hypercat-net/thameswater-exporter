import os
import datetime

from dotenv import load_dotenv
from thameswaterapi import ThamesWater

from tw_readings import lines_to_measurements


load_dotenv()

email = os.environ['EMAIL']
password = os.environ['PASSWORD']
account_number = int(os.environ['ACCOUNT_NUMBER'])
meter = int(os.environ['METER'])

def test_hourly_reading_retrieval():
    thames_water = ThamesWater(email=email, password=password, account_number=account_number)

    start = datetime.date(2025, 2, 11)
    end = datetime.date(2025, 2, 16)

    meter_usage = thames_water.get_meter_usage(
        meter,
        datetime.datetime.combine(start, datetime.time.min),
        datetime.datetime.combine(end, datetime.time.min),
    )
    readings = lines_to_measurements(start, meter_usage.Lines)

    assert len(readings) > 0
