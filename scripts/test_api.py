#!/usr/bin/env python3
"""Live Thames Water API smoke test. Requires Thames Water credentials in .env."""

from __future__ import annotations

import datetime
import os
import sys

from dotenv import load_dotenv
from thameswaterapi import ThamesWater

from thameswater_exporter.readings import lines_to_measurements

load_dotenv()

REQUIRED = (
    "THAMESWATER_EMAIL",
    "THAMESWATER_PASSWORD",
    "THAMESWATER_ACCOUNT_NUMBER",
    "THAMESWATER_METER",
)


def main() -> int:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}", file=sys.stderr)
        print("Copy .env.example to .env and fill in your Thames Water login.", file=sys.stderr)
        return 1

    email = os.environ["THAMESWATER_EMAIL"]
    account_number = int(os.environ["THAMESWATER_ACCOUNT_NUMBER"])
    meter = int(os.environ["THAMESWATER_METER"])
    password = os.environ["THAMESWATER_PASSWORD"]

    end = datetime.date.today()
    start = end - datetime.timedelta(days=6)

    print(f"Logging in as {email!r}, account {account_number}, meter {meter}")
    print(f"Fetching hourly data {start} .. {end}")

    try:
        client = ThamesWater(email=email, password=password, account_number=account_number)
        usage = client.get_meter_usage(
            meter,
            datetime.datetime.combine(start, datetime.time.min),
            datetime.datetime.combine(end, datetime.time.min),
        )
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2

    print(
        f"IsError={usage.IsError}  IsDataAvailable={usage.IsDataAvailable}  "
        f"IsConsumptionAvailable={usage.IsConsumptionAvailable}"
    )
    print(f"Lines returned: {len(usage.Lines)}")

    if not usage.Lines:
        print("No hourly lines in response.")
        return 3

    readings = lines_to_measurements(start, usage.Lines)
    final = [r for r in readings if not r.is_estimated]
    estimated = [r for r in readings if r.is_estimated]

    print(f"Parsed readings: {len(readings)}  final={len(final)}  estimated={len(estimated)}")
    if readings:
        print(f"Time range: {readings[0].hour_start.isoformat()} -> {readings[-1].hour_start.isoformat()}")

    print("\nFirst 3 lines (raw API):")
    for line in usage.Lines[:3]:
        print(
            f"  Label={line.Label!r}  Usage={line.Usage}  Read={line.Read}  "
            f"IsEstimated={line.IsEstimated}"
        )

    print("\nLast 3 lines (raw API):")
    for line in usage.Lines[-3:]:
        print(
            f"  Label={line.Label!r}  Usage={line.Usage}  Read={line.Read}  "
            f"IsEstimated={line.IsEstimated}"
        )

    if estimated:
        print(f"\nFirst estimated hour: {estimated[0].hour_start.isoformat()}")
        print("(Exporter stops pushing at the first estimated hour.)")

    print("\nOK — API reachable and returning hourly data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
