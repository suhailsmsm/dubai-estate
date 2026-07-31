#!/usr/bin/env python3
"""Build the consolidated Bayut pricing-history dataset for the dubai-estate UI.

Reads the raw collector outputs under data/bayut/ and emits a single
self-contained JS bundle at ui/data/bayut-pricing-history.js that the
pricing-history.html page loads via <script src> (so it works from file://
with no backend or fetch/CORS dependency).

Sources combined
----------------
1. ``area_individual_history_2016_2026.json`` — individual archived Bayut
   asking prices sampled per area/year from the Wayback Machine (2016-2025).
   These are *sampled asking prices from archived area pages*, not verified
   transactions. Years without a usable snapshot are gaps — never invented.
2. ``listings.csv`` — current live asking prices (PropertyFinder snapshot).
   Folded in as the "current" series so each area shows where it is today
   next to its archived history.

Honesty rules (mirrors the app's analytics discipline):
- Every aggregate carries its sample size.
- Every series carries its methodology + caveats.
- No value is fabricated for a missing year; gaps stay gaps.

Run:
    python3 tools/build_bayut_history.py
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "bayut"
OUT_JS = ROOT / "ui" / "data" / "bayut-pricing-history.js"

CURRENT_YEAR = datetime.now(timezone.utc).year
LATEST_LABEL = "current"  # bucket name for the live listings snapshot


def _pct(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile on an already-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _agg(prices: list[float]) -> dict:
    s = sorted(prices)
    return {
        "count": len(s),
        "min": round(s[0], 2),
        "p25": round(_pct(s, 0.25), 2),
        "median": round(statistics.median(s), 2),
        "mean": round(statistics.mean(s), 2),
        "p75": round(_pct(s, 0.75), 2),
        "max": round(s[-1], 2),
    }


def _area_key(area: str, city: str) -> str:
    return f"{area} | {city}"


def load_history() -> tuple[dict, dict, dict]:
    """Return (meta, samples_by_key, history_meta)."""
    raw = json.loads((DATA / "area_individual_history_2016_2026.json").read_text())
    meta = {
        "source_note": raw.get("source_note", ""),
        "last_updated": raw.get("last_updated", ""),
        "years_requested": raw.get("years_requested", []),
        "sample_size_target": raw.get("sample_size_target", 20),
    }
    samples_by_key: dict[str, list[dict]] = defaultdict(list)
    for p in raw.get("prices", []):
        key = _area_key(p["area"], p["city"])
        samples_by_key[key].append(
            {
                "year": p["year"],
                "price": float(p["price"]),
                "property_type": p.get("property_type", "unknown"),
                "sample_index": p.get("sample_index"),
                "source": "Bayut archive (Wayback Machine)",
                "source_url": p.get("source_url", ""),
                "snapshot_timestamp": p.get("snapshot_timestamp", ""),
                "confidence": p.get("confidence", "low"),
                "kind": "archive",
            }
        )
    return meta, samples_by_key, raw


def load_current_listings() -> dict[str, list[dict]]:
    """Fold live listings in as the 'current' bucket. Rents annualized already
    are stored as the asking price; sales stay as-is. Kept per (area, city)."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    path = DATA / "listings.csv"
    if not path.exists():
        return by_key
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                price = float(row["price"])
            except (TypeError, ValueError):
                continue
            area = (row.get("area") or "").strip()
            city = (row.get("city") or "").strip().lower()
            if not area or not city or price <= 0:
                continue
            key = _area_key(area, city)
            by_key[key].append(
                {
                    "year": LATEST_LABEL,
                    "price": price,
                    "property_type": (row.get("property_type") or "unknown").strip(),
                    "listing_type": (row.get("listing_type") or "").strip(),
                    "bedrooms": row.get("bedrooms"),
                    "baths": row.get("bathrooms"),
                    "area_sqft": row.get("area_sqft"),
                    "source": "PropertyFinder (live snapshot)",
                    "source_url": row.get("url", ""),
                    "posted_date": row.get("posted_date", ""),
                    "confidence": "medium",
                    "kind": "current",
                }
            )
    return by_key


def build() -> dict:
    hist_meta, hist_samples, raw = load_history()
    current = load_current_listings()

    # Union of all (area, city) keys.
    keys = sorted(set(hist_samples) | set(current))

    areas = []
    for key in keys:
        area_name, city = [p.strip() for p in key.split("|", 1)]

        # Bucket samples by year. Archive years are ints; current is the label.
        by_year: dict[object, list[float]] = defaultdict(list)
        by_year_samples: dict[object, list[dict]] = defaultdict(list)
        for s in hist_samples.get(key, []):
            by_year[s["year"]].append(s["price"])
            by_year_samples[s["year"]].append(s)
        # Split current listings into rent/sale; store rent as the comparable
        # (archive data is rentals), but keep sale too.
        cur_rent = [s for s in current.get(key, []) if s.get("listing_type") == "rent"]
        cur_sale = [s for s in current.get(key, []) if s.get("listing_type") == "sale"]
        if cur_rent:
            by_year[LATEST_LABEL] = [s["price"] for s in cur_rent]
            by_year_samples[LATEST_LABEL] = cur_rent
        if cur_sale:
            by_year["current_sale"] = [s["price"] for s in cur_sale]
            by_year_samples["current_sale"] = cur_sale

        year_keys = sorted(
            by_year.keys(),
            key=lambda y: (y == LATEST_LABEL, y == "current_sale", y)
            if isinstance(y, int)
            else (y == "current_sale", True, 9999),
        )

        series = []
        for y in year_keys:
            prices = by_year[y]
            if not prices:
                continue
            entry = {"year": y, **_agg(prices)}
            if y == LATEST_LABEL:
                entry["label"] = "Current (live rent)"
                entry["source"] = "PropertyFinder"
            elif y == "current_sale":
                entry["label"] = "Current (live sale)"
                entry["source"] = "PropertyFinder"
            else:
                entry["label"] = str(y)
                entry["source"] = "Bayut archive"
            series.append(entry)

        if not series:
            continue

        # Build chart-friendly numeric timeline (rent comparables only).
        numeric = [
            {"x": y if isinstance(y, int) else CURRENT_YEAR, "year": y, **_agg(by_year[y])}
            for y in year_keys
            if y in (LATEST_LABEL,) or isinstance(y, int)
        ]
        # Drop the sale-only current bucket from the rent timeline.
        numeric = [p for p in numeric if not (isinstance(p["year"], str) and p["year"] == "current_sale")]

        areas.append(
            {
                "area": area_name,
                "city": city,
                "key": key,
                "series": series,  # table rows incl. current sale
                "timeline": numeric,  # chart points (rent comparables)
                "samples": by_year_samples,
                "sample_total": sum(len(v) for v in by_year_samples.values()),
            }
        )

    cities = sorted({a["city"] for a in areas})
    years_present = sorted(
        {y for a in areas for p in a["timeline"] if isinstance(p["year"], int) for y in [p["year"]]}
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "methodology": (
            "Median annual asking rent per area, in AED. Historical points are "
            "sampled asking rents scraped from archived Bayut area pages via the "
            "Wayback Machine (one snapshot per area/year). The final point is the "
            "median of a live PropertyFinder rent snapshot. These are ASKING "
            "PRICES, not registered DLD transactions or Ejari contracts — treat "
            "as directional market sentiment, not exact market value."
        ),
        "caveats": [
            "Asking prices, not transacted/registered prices.",
            "Archive points are a sample (target ~20/year) from a single mid-year snapshot per area.",
            "Different properties each year — medians are subject to mix shift.",
            f"Years with no usable snapshot are gaps (none of: {', '.join(map(str, sorted(set(raw.get('years_requested', [])) - set(years_present)))) or 'n/a'}).",
            "Cross-city comparisons are rough: currency AED, but markets differ structurally.",
        ],
        "cities": cities,
        "years_present": years_present,
        "areas": areas,
        "source_note": hist_meta["source_note"],
        "source_last_updated": hist_meta["last_updated"],
    }


def main() -> None:
    payload = build()
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    # Compact but valid JS: assign to window global. No JSON.parse needed.
    js = "/* Auto-generated by tools/build_bayut_history.py — do not edit. */\n"
    js += "window.BAYUT_HISTORY = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    OUT_JS.write_text(js, encoding="utf-8")

    n_areas = len(payload["areas"])
    n_samples = sum(a["sample_total"] for a in payload["areas"])
    print(f"Wrote {OUT_JS.relative_to(ROOT)}")
    print(f"  areas: {n_areas}  | samples: {n_samples}  | cities: {len(payload['cities'])}")
    print(f"  years: {payload['years_present']}")


if __name__ == "__main__":
    main()
