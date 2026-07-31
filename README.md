# Dubai Real Estate Analytics

An analytical platform for the Dubai real estate market: which districts and
projects are actually appreciating, how sale prices and rents move over
time, and where gross yield looks best — based on real registered
transactions, not asking prices.

The core idea is to ground everything in **real, verifiable data with a
traceable source** — every stored record keeps a reference back to where it
came from (a government open-data API, a specific dataset, or OpenStreetMap)
— rather than estimates or scraped listing prices.

## What's here today

Only the data layer is built so far: a Postgres star schema plus a Python
ELT service that collects, normalizes, and enriches the data. A REST API and
a map UI are planned but not started (see [Roadmap](#roadmap)).

## Data sources

| Source | What it provides | Coverage |
|---|---|---|
| [Dubai Land Department open-data gateway](https://dubailand.gov.ae/en/open-data/real-estate-data/) | Live government transactions, rents, projects | **2026 only** — the gateway has a hard cutoff at the start of the current year, verified empirically |
| [Kaggle: alexefimik](https://www.kaggle.com/datasets/alexefimik/dubai-real-estate-transactions-dataset) / [austinpowers](https://www.kaggle.com/datasets/austinpowers/dubai-real-estate-transaction-first-semester-2023) | Historical DLD transaction mirrors (CC0) | 1995-03-07 → 2023-06-26, deduplicated against each other (see [docs/CSV_DATA_ANALYSIS.md](docs/CSV_DATA_ANALYSIS.md)) |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) (via Nominatim) | Area centroids and boundary polygons | 319/439 areas have coordinates, 189/439 have real boundary polygons (see [docs/OSM_AREA_GEO_ENRICHMENT.md](docs/OSM_AREA_GEO_ENRICHMENT.md)) |

**Known gap**: mid-2023 through 2025 isn't covered by any source yet — the
live gateway only reaches back to 2026 and the historical CSVs stop at
mid-2023. Options were researched (PropAPIS, Property Monitor) but not
pursued — see [docs/PLAN.md](docs/PLAN.md) for the reasoning.

Combined: **1,233,571 sale transactions** and **484,485 rent contracts**
across every source, with zero double-counting.

## Repository layout

```
dubai-estate/
├── docker-compose.yml   # local stack: Postgres+PostGIS, the ELT service
├── data/raw/            # downloaded historical CSVs (gitignored — see docs/CSV_DATA_ANALYSIS.md)
├── docs/
│   ├── PLAN.md                      # architecture, schema design, source research
│   ├── CSV_DATA_ANALYSIS.md         # historical-CSV format comparison & dedup analysis
│   └── OSM_AREA_GEO_ENRICHMENT.md   # area geocoding methodology & results
├── elt/                  # the ELT service — see elt/README.md
└── .githooks/            # tracked pre-commit hook (ruff)
```

## The ELT component (`elt/`)

A Python service (FastAPI-adjacent tooling, SQLAlchemy 2.0, Alembic, Typer
CLI) that turns the raw sources above into a normalized Postgres **star
schema**: dimension tables for areas, projects, developers, and property
types; fact tables for sale transactions and rent contracts; and monthly
analytics marts (median price/m², percentiles, gross yield) rebuilt after
every load.

Every fact row carries `source_id` / `source_url` / `source_ref` for
provenance, and every source is flagged `is_government` so any query can
filter to verified government data only or include the historical/OSM
enrichment too.

**Runs as three kinds of work**, all sharing the same
collect → transform → enrich-geo → rebuild-marts pipeline:
- **Scheduled daily** (`dxb run-scheduler`) — incremental, watermark-based,
  retried with backoff and cancellation-aware (SIGTERM → marked `cancelled`,
  not stuck at `running`).
- **One-off backfills** (`dxb backfill --from ... --to ...`) — the same
  pipeline over an explicit historical range, resumable if interrupted.
- **One-off imports** (`dxb import-csv`, `dxb enrich-geo`) — the historical
  CSV load and the OSM geocoding sweep, each documented in `docs/`.

See [elt/README.md](elt/README.md) for how to run it locally.

## Roadmap

- [x] Star-schema Postgres design + Alembic migrations
- [x] Live DLD gateway collector (daily scheduler, backfill, retries, alerting)
- [x] Historical CSV import with cross-source deduplication
- [x] OSM area geo-enrichment (centroids + boundary polygons)
- [ ] REST API (FastAPI) over the marts/facts
- [ ] ML price/rent forecasting
- [ ] Map UI
