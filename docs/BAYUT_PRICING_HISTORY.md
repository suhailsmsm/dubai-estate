# Bayut Pricing History (asking-price analysis, 2016–current)

Adds archived Bayut asking-price history plus a live PropertyFinder snapshot to
the Dubai Estate app, so you can **see the pricing-history analysis** without
needing the Postgres stack running.

> Self-contained: open `ui/pricing-history.html` directly in a browser. No
> Docker, no API, no internet (apart from the Chart.js CDN).

## What's in it

Two datasets, copied verbatim from `property-market-analyzer` into
`data/bayut/`:

| File | What | Rows |
|---|---|---|
| `area_individual_history_2016_2026.json` / `.csv` | Individual archived **Bayut** asking rents sampled per area/year from the Wayback Machine (one mid-year snapshot per area/year, target ~20/year) | 2,432 prices · 26 areas · 4 cities |
| `listings.csv` | **Live** asking prices (PropertyFinder snapshot, rent + sale) | 945 listings |
| `area_history.json`, `area_history_2024_2026.json` | Pre-aggregated min/max/avg/median per area/year (reference) | — |

Coverage: **2016, 2018–2025** archive (2017 and 2026 have no usable snapshot —
reported as gaps, never invented), plus a `current` point from the live
snapshot. Cities: Dubai (1,065), Abu Dhabi (839), Sharjah (453), Al Ain (75).

## Files added

```
data/bayut/                              # raw collector outputs (source of truth)
tools/build_bayut_history.py             # builds the consolidated dataset
ui/data/bayut-pricing-history.js         # GENERATED — window.BAYUT_HISTORY bundle
ui/pricing-history.html                  # standalone analysis page
ui/index.html                            # + "📈 Pricing History" link in the header
```

## Regenerating the dataset

After refreshing the raw files under `data/bayut/`:

```bash
python3 tools/build_bayut_history.py
```

The generator combines the archive series with the live rent snapshot, computes
per-area/per-year aggregates (count, min, P25, **median**, mean, P75, max) and
writes `ui/data/bayut-pricing-history.js`. The HTML page reads that file via a
plain `<script src>` so it works from `file://` (no fetch/CORS).

## What the page shows

- **Single-area mode** — hero stats (latest archive median, live asking, CAGR,
  range), a median-rent timeline with interquartile-range bars, a full annual
  breakdown table (with sample sizes), and the methodology + caveats panel.
- **Compare mode** — multi-line timeline (up to 6 areas) and a cumulative-change
  table (first→last archive point, total %, CAGR) with per-row sample tiers.

Sample-size tiers: `high` (n≥15), `medium` (n≥8), `low` (n<8).

## Honesty rules (mirrors the rest of the app)

Every aggregate carries its sample size and the response carries its
methodology and caveats. These are **asking prices**, not registered DLD
transactions or Ejari contracts — treat them as directional market sentiment,
not exact market value. Different properties are sampled each year, so medians
are subject to mix shift.

---

## Backend integration path (when Postgres is up)

The star schema already declares `FactListing` ("asking prices from listing
portals — phase 2") but **no migration creates the table yet**, and no ELT
loader ingests listings. To fold this data into the governed star schema (so it
joins with DLD transactions/rents and powers mart-based endpoints):

1. **Migration** — add an Alembic revision under `elt/alembic/versions/` that
   creates `fact_listing` (the columns already exist on the model in
   `packages/dxb-core/src/dxb_core/models.py`).
2. **Source row** — seed `dim_source` with `code='bayut_archive'`,
   `is_government=false` (the trust-separation flag already on `DimSource`).
3. **Loader** — add an ELT collector/transform under `elt/src/dxb/` that maps
   `data/bayut/area_individual_history_2016_2026.json` → `fact_listing`
   (area-resolved via `dim_area`, `purpose='for-rent'`,
   `external_id = f"{area}:{year}:{sample_index}"`, `first_seen`/`last_seen`
   from `snapshot_timestamp`, `price_aed` from `price`).
4. **Mart** — extend the area/project monthly marts with an asking-price column,
   or add a dedicated `mart_asking_*` (asking prices are sampled yearly, so a
   monthly grain would be sparse — yearly is more honest).
5. **API** — a read endpoint (e.g. `GET /analytics/asking-history`) in
   `api/src/dxb_api/routers/` returning the same shape `pricing-history.html`
   consumes today, with `methodology` + `caveats`.

Note: the Docker stack was not running when this feature was added, so the
self-contained HTML page is the working/verified view; the steps above are the
upgrade path into the governed backend.
