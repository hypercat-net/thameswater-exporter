# thameswater-exporter

[![CI](https://github.com/hypercat-net/thameswater-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/hypercat-net/thameswater-exporter/actions/workflows/ci.yml) [![License](https://img.shields.io/github/license/hypercat-net/thameswater-exporter)](https://github.com/hypercat-net/thameswater-exporter/blob/main/LICENSE) [![Docker](https://img.shields.io/docker/v/hypercat42/thameswater-exporter?label=docker)](https://hub.docker.com/r/hypercat42/thameswater-exporter)

Pushes your **hourly** Thames Water smart-meter readings into **Mimir** using
the Prometheus `remote_write` protocol, so you can graph and alert on household
water usage in Grafana.

[![BuyMeACoffee](https://raw.githubusercontent.com/barcar/buymeacoffee-badges/main/bmc-donate-white.svg)](https://buymeacoffee.com/barcar)

It uses [jelmer/thameswaterapi](https://github.com/jelmer/thameswaterapi) (PyPI:
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

- `THAMESWATER_EXPORTER_BACKFILL_DAYS` is **clamped to 7** — older hourly data does not exist.
- **Run the exporter at least every few days.** If it is down for longer than 7
  days, the missed hours age out of Thames Water permanently; the exporter logs
  an "unrecoverable gap" warning and resumes from the start of the 7-day window.
  (The default `THAMESWATER_EXPORTER_POLL_INTERVAL_SECONDS=3600` keeps you well inside this.)
- The 7-day window fits in a single request, so chunking (`THAMESWATER_EXPORTER_CHUNK_DAYS`) is only
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
| `thameswater_hourly_volumetric_cost_gbp` | gauge | derived | Estimated volumetric cost for that hour (`Usage` × current tariff £/m³). |

Each collection cycle also pushes **snapshot** gauges (timestamp = fetch time, not
`hour_start`):

| Metric | Source | Meaning |
| --- | --- | --- |
| `thameswater_tariff_clean_water_rate_gbp_per_m3` | `get_tariff()` | Published clean-water volumetric rate |
| `thameswater_tariff_wastewater_rate_gbp_per_m3` | `get_tariff()` | Published wastewater volumetric rate |
| `thameswater_tariff_water_standing_charge_gbp_per_day` | `get_tariff()` | Water fixed charge ÷ 365 |
| `thameswater_tariff_wastewater_standing_charge_gbp_per_day` | `get_tariff()` | Wastewater fixed charge ÷ 365 |
| `thameswater_account_current_balance_gbp` | `get_account()` | Account `currentBalance` |

Tariff figures are region-wide (scraped from Thames Water's public Scheme of
Charges). Volumetric cost is an estimate from published rates, not your actual
bill. Standing charges are exported separately and are **not** included in hourly
cost. Tariff rates are cached in `state.json` after a successful fetch and
reused when the tariff page is unavailable. If tariff fetch fails and no cache
exists, cost metrics are skipped for that cycle. Account fetch failures skip
account metrics only.

`thameswaterapi` does not currently expose a `totalBalance` field — only
`currentBalance` from the account-management API.

Labels: `meter`, `account`, `serial` (+ anything in `THAMESWATER_EXPORTER_EXTRA_LABELS`).

Example queries:

```promql
# litres used per hour
increase(thameswater_meter_reading_litres_total[1h])

# litres used per day
increase(thameswater_meter_reading_litres_total[1d])

# estimated volumetric cost per hour (GBP)
thameswater_hourly_volumetric_cost_gbp
```

The exporter also serves its own health on `:9100`:

| Path | Purpose |
| --- | --- |
| `/` or `/status` | Human-readable status (timestamps as `YYYY-MM-DD HH:MM:SS UTC` with “x ago”, last published meter reading) |
| `/healthz` | Liveness probe (`ok`) |
| `/metrics` | Prometheus self-metrics (`thameswater_exporter_up`, freshness timestamps, etc.) |

Water readings are **not** on these endpoints; they are pushed to Mimir via `remote_write`.
Only the self-metrics are real-time and safe to scrape normally.

### Why not Prometheus or Alloy?

**Prometheus alone** cannot receive water readings. Prometheus is pull-based: it
scrapes `/metrics` and stamps every sample with *scrape time*. It has no endpoint
that accepts incoming `remote_write` pushes, so there is nowhere to send
backdated hourly data even if you wanted to. You can scrape `:9100` for exporter
health, but not for `thameswater_meter_reading_litres_total` with correct
timestamps.

**Grafana Alloy** (`prometheus.receive_http` → `prometheus.remote_write`) is
also a poor fit. In production, backdated samples were dropped as out-of-order
in Alloy's remote_write WAL while the exporter reported success — data never
reached storage. Alloy is still fine for scraping the exporter's `:9100` health
metrics; this project does not support routing water readings through it.

You need a backend that **accepts Prometheus `remote_write` with historical
timestamps** and tolerates a 7-day backfill. This exporter targets **Mimir**
(`/api/v1/push`). Other receivers (e.g. VictoriaMetrics, Cortex, Thanos
Receive) may work with the right URL and retention settings, but are **out of
scope** for this documentation.

## Architecture

```
Thames Water API ──► exporter ──remote_write(historical ts)──► Mimir  /api/v1/push
                                                                (X-Scope-OrgID header)
```

Scrape the exporter's own `:9100` health metrics with Prometheus or Alloy if you
like; only the **water readings** use `remote_write` with backdated timestamps.

## Quick start (local test stack)

The compose file runs the exporter alongside a **local** Mimir for testing.
`config/mimir/mimir.yaml` is for this stack only — **do not apply it wholesale
to an existing Mimir instance.**

```bash
cp .env.example .env      # fill in THAMESWATER_* credentials
docker compose up -d
```

Then:

- Exporter health: <http://localhost:9100/status> (or `/metrics` for Prometheus)
- Query Mimir with a **range** query (tenant `anonymous` in the local stack). An
  query at "now" is often empty because readings are backdated — see
  [Querying in Grafana](#querying-in-grafana) below. Adjust `start`/`end` to
  your backfill window after the exporter's first run:

```bash
curl -sG 'http://localhost:9009/prometheus/api/v1/query_range' \
  --data-urlencode 'query=thameswater_meter_reading_litres_total' \
  --data-urlencode 'start=2026-06-28T00:00:00Z' \
  --data-urlencode 'end=2026-07-02T00:00:00Z' \
  --data-urlencode 'step=3600' \
  -H 'X-Scope-OrgID: anonymous'
```

## Using with your existing Mimir

Run only the exporter container and push readings straight to Mimir's distributor.

1. **Configure the exporter** (`.env` or container env):

   ```bash
   THAMESWATER_EMAIL=...
   THAMESWATER_PASSWORD=...
   THAMESWATER_ACCOUNT_NUMBER=...
   THAMESWATER_METER=...
   THAMESWATER_EXPORTER_REMOTE_WRITE_URL=http://<your-mimir-host>:9009/api/v1/push
   THAMESWATER_EXPORTER_MIMIR_TENANT=<your-tenant>   # e.g. utility
   ```

2. **Run the exporter** (persist `/data` so the high-water-mark survives
   restarts):

   ```bash
   docker compose up -d exporter
   # or: docker run -d --env-file .env -v thameswater-state:/data -p 9100:9100 hypercat42/thameswater-exporter:latest
   ```

3. **Adjust Mimir limits** for your tenant — see [Mimir limits for historical
   remote_write](#mimir-limits-for-historical-remote_write) below.

### Mimir limits for historical remote_write

Backfilled hours arrive with timestamps up to ~7 days in the past. On first run
they are often ingested as **out-of-order** relative to the ingester head. You
may need **both** relaxed ingest limits **and** a wider querier window before
Grafana can see the data.

Set these on the tenant (runtime overrides) or globally in `limits:` (requires
Mimir restart for static config):

```yaml
# Ingest: accept backdated / out-of-order hourly samples (7-day backfill).
out_of_order_time_window: 168h
past_grace_period: 168h

# Query: default query_ingesters_within is 13h — too short for samples still
# in the ingester head. Without this, writes succeed but query_range returns {}.
query_ingesters_within: 168h
```

If writes are rejected, check exporter logs for `sample-out-of-order` or
`sample-too-old`. There is **no** Mimir limit named `reject_old_samples_max_age`;
use `past_grace_period` instead.

[`config/mimir/mimir.yaml`](config/mimir/mimir.yaml) is a **local test** config
only; do not merge it wholesale into a real Mimir — copy only the `limits`
snippets you need.

### Querying in Grafana

Water series have **no sample at "now"** until the latest hour is finalised
(recent hours stay `IsEstimated` for a day or two). Symptoms:

- **`query_range` over the backfill window** — works once Mimir limits above
  are set.
- **Instant query without a time modifier** — often empty; use a time-series
  panel (range query) or an instant query with `@ <unix_ts>` / `@ <rfc3339>`.

Example range query via curl:

```bash
curl -sG 'http://localhost:9009/prometheus/api/v1/query_range' \
  --data-urlencode 'query=thameswater_meter_reading_litres_total' \
  --data-urlencode 'start=2026-06-28T00:00:00Z' \
  --data-urlencode 'end=2026-07-02T00:00:00Z' \
  --data-urlencode 'step=3600' \
  -H 'X-Scope-OrgID: <your-tenant>'
```

## Day-to-day operation

| Event | What happens |
| --- | --- |
| **First run** (no state file) | Logs in to Thames Water, fetches the last 7 days of hourly data, pushes every **finalised** hour to Mimir, saves high-water-mark to `THAMESWATER_EXPORTER_STATE_FILE`. |
| **Each poll** (default hourly) | Re-authenticates, fetches from the high-water-mark day through today, pushes any newly finalised hours, stops at the first `IsEstimated` hour (not ready yet). |
| **Restart** | Resumes from `THAMESWATER_EXPORTER_STATE_FILE`; does not re-push hours already sent. |
| **Down > 7 days** | Hours before the rolling 7-day window are gone from Thames Water; exporter logs an **unrecoverable gap** warning and resumes from the oldest available hour. |

Check `thameswater_exporter_up` and `thameswater_exporter_last_success_timestamp_seconds`
on `:9100/metrics` to confirm the exporter is running. For data freshness:

| Metric | Meaning |
| --- | --- |
| `last_success_timestamp_seconds` | Last collection cycle completed without error (since restart) |
| `last_new_data_push_timestamp_seconds` | Last time one or more **new** finalised hours were pushed (persisted) |
| `last_pushed_hour_timestamp_seconds` | `hour_start` of the newest hour in storage (persisted high-water-mark) |
| `last_pushed_reading_litres` | Cumulative meter reading (litres) at the newest pushed hour (persisted) |
| `samples_pushed_total` | Samples pushed via `remote_write` since restart |
| `push_errors_total` | Failed collection/push cycles since restart |

Example alerts: no successful cycles for 2h; no new data push for 48h; high-water-mark
more than 72h behind now.

## Configuration

All via environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
| --- | --- | --- |
| `THAMESWATER_EMAIL`, `THAMESWATER_PASSWORD`, `THAMESWATER_ACCOUNT_NUMBER`, `THAMESWATER_METER` | — | Thames Water login + meter (required) |
| `THAMESWATER_EXPORTER_REMOTE_WRITE_URL` | `http://mimir:9009/api/v1/push` | Mimir distributor `/api/v1/push` |
| `THAMESWATER_EXPORTER_BACKFILL_DAYS` | `7` | History to load on first run (clamped to 7 — the hourly limit) |
| `THAMESWATER_EXPORTER_CHUNK_DAYS` | `7` | Days of data fetched per request |
| `THAMESWATER_EXPORTER_CHUNK_DELAY_SECONDS` | `1` | Pause between backfill requests |
| `THAMESWATER_EXPORTER_POLL_INTERVAL_SECONDS` | `3600` | How often to check for new finalised hours |
| `THAMESWATER_EXPORTER_STATE_FILE` | `/data/state.json` | High-water-mark (last pushed hour) |
| `THAMESWATER_EXPORTER_HEALTH_PORT` | `9100` | Self `/healthz` + `/metrics` |
| `THAMESWATER_EXPORTER_LOG_LEVEL` | `INFO` | Logging verbosity |
| `THAMESWATER_EXPORTER_EXTRA_LABELS` | — | e.g. `location=home,env=prod` |
| `THAMESWATER_EXPORTER_MIMIR_TENANT` | — | **Required** for direct Mimir push (`X-Scope-OrgID` header) |
| `THAMESWATER_EXPORTER_REMOTE_WRITE_USERNAME` / `_PASSWORD` / `_BEARER_TOKEN` | — | Optional auth on the remote_write endpoint |

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

## CI / Docker image

GitHub Actions runs `pytest` on every push and pull request. Pushes to `main`
(and version tags `v*`) also build and publish
[`hypercat42/thameswater-exporter`](https://hub.docker.com/r/hypercat42/thameswater-exporter)
to Docker Hub. A **weekly scheduled rebuild** (Sundays 04:17 UTC) refreshes
`latest` against the current `python:3.12-slim` base even when application code
has not changed — useful for picking up base-image CVE fixes.

Configure these [repository secrets](https://github.com/hypercat-net/thameswater-exporter/settings/secrets/actions):

| Secret | Description |
| --- | --- |
| `DOCKERHUB_USERNAME` | Your Docker Hub username (`hypercat42`) |
| `DOCKERHUB_TOKEN` | Docker Hub [access token](https://hub.docker.com/settings/security) |

Tags: `latest` and `sha-<commit>` on every `main` push and weekly rebuild;
`1.4.2`, `1.4`, and `1` when you push a version tag (e.g. `v1.4.2`). Images
are published for `linux/amd64` and `linux/arm64`. A weekly workflow deletes
`sha-*` tags older than 90 days (semver and `latest` are never removed); run
[Prune Docker sha tags](https://github.com/hypercat-net/thameswater-exporter/actions/workflows/prune-docker-tags.yml)
manually with **dry run** first to preview.

Pin production to a semver or `sha-` tag; use `latest` only if you pull
regularly (or rely on the weekly rebuild) to stay on patched base layers.
