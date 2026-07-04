# thameswater-exporter

Pushes your **hourly** Thames Water smart-meter readings into **Mimir** (via
**Grafana Alloy**) using the Prometheus `remote_write` protocol, so you can graph
and alert on household water usage in Grafana.

It uses [**thameswaterapi**](https://github.com/jelmer/thameswaterapi) (PyPI:
`thameswaterapi`) for Thames Water authentication and API access — a maintained
fork of [AyrtonB/Thames-Water](https://github.com/AyrtonB/Thames-Water/). Exporter-specific
logic (finalised-hour filtering, `remote_write` push, state) lives in the
`thameswater_exporter` package; reading metadata (`is_estimated`, `serial`) is
added in `thameswater_exporter.readings`.

## Why this isn't a normal `/metrics` scrape

Thames Water readings are **not real time**. Recent hours show up a day or two
late and are flagged `IsEstimated` until finalised. A scraped `/metrics`
endpoint would stamp every value with *scrape time*, putting your water usage at
the wrong point on the timeline.

Instead, this exporter **pushes each hourly reading with its real `hour_start`
timestamp** via `remote_write`, and tracks a per-meter **high-water-mark** so it:

- only sends hours that are **finalised** (`IsEstimated == false`),
- sends every finalised hour **exactly once**, in **strictly increasing**
  timestamp order (no duplicates, no re-ordering),
- resumes correctly after restarts (state is persisted).

### Hourly data is only available for the last 7 days

Thames Water exposes different resolutions for different time ranges:

| View | Resolution | History available |
| --- | --- | --- |
| daily | **hourly** | last **7 days** |
| monthly | daily | last 12 months |
| half-yearly | monthly | last 3 years |
| yearly | monthly | last 6 years |

This exporter targets the **hourly** feed, so it can only ever see the **last 7
days** of hourly readings. Consequences:

- `BACKFILL_DAYS` is **clamped to 7** — older hourly data does not exist.
- **Run the exporter at least every few days.** If it is down for longer than 7
  days, the missed hours age out of Thames Water permanently; the exporter logs
  an "unrecoverable gap" warning and resumes from the start of the 7-day window.
  (The default `POLL_INTERVAL_SECONDS=3600` keeps you well inside this.)
- The 7-day window fits in a single request, so chunking (`CHUNK_DAYS`) is only
  relevant if you later fetch the coarser/longer feeds. Any window that reaches
  before the 7-day horizon and comes back clipped is skipped with a warning
  rather than written misaligned.

### What gets stored

Thames Water returns both interval `Usage` (litres per hour) and cumulative
`Read` (the meter dial in litres at end of each hour). For finalised hours we
push `Read` directly as the counter — it matches the physical meter and needs no
integration or extra state.

| Metric | Type | Source | Meaning |
| --- | --- | --- | --- |
| `thameswater_meter_reading_litres_total` | counter | `Read` | Cumulative meter reading (litres). Use `increase()` / `rate()`. |
| `thameswater_hourly_usage_litres` | gauge | `Usage` | Litres used during that hour. |

Labels: `meter`, `account`, `serial` (+ anything in `EXTRA_LABELS`).

Example queries:

```promql
# litres used per hour
increase(thameswater_meter_reading_litres_total[1h])

# litres used per day
increase(thameswater_meter_reading_litres_total[1d])
```

The exporter also serves its own health on `:9100` (`/healthz`, `/metrics`) with
`thameswater_exporter_up`, `*_last_success_timestamp_seconds`,
`*_samples_pushed_total`, etc. Those are real-time and safe to scrape normally.

## Architecture

```
Thames Water API ──► exporter ──remote_write(historical ts)──► Alloy ──► Mimir
                                  prometheus.receive_http :9999   /api/v1/push
```

## Quick start (local test stack)

The compose file runs the exporter alongside a **local** Alloy and Mimir for
testing. The files under `config/` are for this stack only — **do not apply them
to an existing Alloy or Mimir instance.**

```bash
cp .env.example .env      # fill in EMAIL / PASSWORD / ACCOUNT_NUMBER / METER
docker compose up --build
```

Then:

- Exporter health: <http://localhost:9100/metrics>
- Alloy UI: <http://localhost:12345>
- Query Mimir (single-tenant `anonymous`):

```bash
curl -s 'http://localhost:9009/prometheus/api/v1/query?query=thameswater_meter_reading_litres_total' \
  -H 'X-Scope-OrgID: anonymous'
```

## Using with your existing Alloy + Mimir

This is the intended production setup: run only the exporter, and point it at
Alloy.

1. **Add a receiver to your existing Alloy** (pick a free port; forward to your
   *existing* `prometheus.remote_write` — it already has the right Mimir URL,
   auth, and tenant):

   ```alloy
   prometheus.receive_http "thameswater" {
     http {
       listen_address = "0.0.0.0"
       listen_port    = 9999   // any free port
     }
     forward_to = [prometheus.remote_write.YOUR_EXISTING.receiver]
   }
   ```

   `prometheus.receive_http` does **not** forward incoming HTTP headers, so set
   `X-Scope-OrgID` (and any auth) on your existing `prometheus.remote_write`,
   not on the exporter. See [`config/alloy/config.alloy`](config/alloy/config.alloy)
   for a minimal example of the receiver pattern.

2. **Configure the exporter** (`.env` or container env):

   ```bash
   EMAIL=...
   PASSWORD=...
   ACCOUNT_NUMBER=...
   METER=...
   REMOTE_WRITE_URL=http://<your-alloy-host>:9999/api/v1/metrics/write
   ```

3. **Run the exporter** (persist `/data` so the high-water-mark survives
   restarts):

   ```bash
   docker compose up --build exporter
   # or: docker build -t thameswater-exporter . && docker run -d --env-file .env -v thameswater-state:/data -p 9100:9100 thameswater-exporter
   ```

4. **Mimir** — you probably need **no changes**. Samples are at most ~7 days
   old and are pushed in timestamp order, which fits inside Mimir's default
   acceptance window (~14 days). Only if writes are rejected (look for
   `err-mimir-sample-timestamp-too-old` or `sample-out-of-order` in exporter
   logs) relax limits for your tenant, e.g. via runtime overrides:

   ```yaml
   reject_old_samples_max_age: 14d
   out_of_order_time_window: 168h
   ```

   [`config/mimir/mimir.yaml`](config/mimir/mimir.yaml) is a **local test**
   config only; do not merge it into a real Mimir.

## Day-to-day operation

| Event | What happens |
| --- | --- |
| **First run** (no state file) | Logs in to Thames Water, fetches the last 7 days of hourly data, pushes every **finalised** hour to Alloy, saves high-water-mark to `STATE_FILE`. |
| **Each poll** (default hourly) | Re-authenticates, fetches from the high-water-mark day through today, pushes any newly finalised hours, stops at the first `IsEstimated` hour (not ready yet). |
| **Restart** | Resumes from `STATE_FILE`; does not re-push hours already sent. |
| **Down > 7 days** | Hours before the rolling 7-day window are gone from Thames Water; exporter logs an **unrecoverable gap** warning and resumes from the oldest available hour. |

Check `thameswater_exporter_up` and `thameswater_exporter_last_success_timestamp_seconds`
on `:9100/metrics` to confirm it is keeping up.

## Configuration

All via environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
| --- | --- | --- |
| `EMAIL`, `PASSWORD`, `ACCOUNT_NUMBER`, `METER` | — | Thames Water login + meter (required) |
| `REMOTE_WRITE_URL` | `http://alloy:9999/api/v1/metrics/write` | Alloy receiver |
| `BACKFILL_DAYS` | `7` | History to load on first run (clamped to 7 — the hourly limit) |
| `CHUNK_DAYS` | `7` | Days of data fetched per request |
| `CHUNK_DELAY_SECONDS` | `1` | Pause between backfill requests |
| `POLL_INTERVAL_SECONDS` | `3600` | How often to check for new finalised hours |
| `STATE_FILE` | `/data/state.json` | High-water-mark (last pushed hour) |
| `HEALTH_PORT` | `9100` | Self `/healthz` + `/metrics` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `EXTRA_LABELS` | — | e.g. `location=home,env=prod` |
| `REMOTE_WRITE_USERNAME` / `_PASSWORD` / `_BEARER_TOKEN`, `MIMIR_TENANT` | — | Only if pushing **directly** to Mimir, bypassing Alloy |

## Using thameswaterapi directly

The exporter depends on the PyPI package. To query Thames Water outside the
exporter:

```python
import datetime
from thameswaterapi import ThamesWater
from thameswater_exporter.readings import lines_to_measurements

tw = ThamesWater(email="me@example.com", password="…", account_number=123456789)

start = datetime.date(2025, 2, 11)
end = datetime.date(2025, 2, 16)
meter_usage = tw.get_meter_usage(
    123456789,
    datetime.datetime.combine(start, datetime.time.min),
    datetime.datetime.combine(end, datetime.time.min),
)
readings = lines_to_measurements(start, meter_usage.Lines)
# -> list[Measurement(hour_start, usage, total, is_estimated, serial)]
```

See the [thameswaterapi README](https://github.com/jelmer/thameswaterapi) for
daily/monthly feeds, listing meters, tariff data, and the CLI.

## Development

```bash
pip install -e ".[dev]"
pytest                             # offline tests in tests/
python scripts/test_api.py         # live API smoke test (needs .env)
```

Package layout:

```
src/thameswater_exporter/
  main.py          # entrypoint loop
  config.py        # environment configuration
  collector.py     # fetch, filter, push
  readings.py      # Measurement adapter over thameswaterapi
  remote_write.py  # Prometheus payload builder
  state.py         # high-water-mark persistence
  health.py        # :9100 /metrics and /healthz
tests/
```
