#!/usr/bin/env python3
"""Pre-compute structured market insights for the AI assistant.

The AI assistant reasons over a *compact, trustworthy context* rather than raw
rows. This script turns the bundled Bayut history + live listings into a small
JSON bundle the chat page injects as system context — so the model answers
grounded in real numbers (median rent, CAGR, gross yield, underpriced flags)
instead of inventing them.

Outputs ``ui/data/market-insights.js`` (``window.MARKET_INSIGHTS``).

Run:
    python3 tools/build_market_insights.py

All figures are AED. Honesty rules mirror the rest of the app: every number
carries its sample size; gaps are never filled; asking prices are flagged as
directional, not exact market value.
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
OUT_JS = ROOT / "ui" / "data" / "market-insights.js"


def _pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _med(vals):
    s = [v for v in vals if v and v > 0]
    return statistics.median(s) if s else None


def _despike(points, max_ratio=4.0):
    """Drop archived yearly medians that spike >max_ratio vs BOTH neighbours.

    These are almost always a sale-priced unit leaking into a rent snapshot
    (e.g. 55k rent -> 3.3M next year), not real appreciation. A genuine rise
    touches at least one neighbour within ratio, so this preserves real trends.
    """
    if len(points) < 3:
        return points
    keep = []
    for i, p in enumerate(points):
        med = p["median"]
        if not med:
            continue
        lo = points[i - 1]["median"] if i > 0 else None
        hi = points[i + 1]["median"] if i < len(points) - 1 else None
        too_far = True
        for nb in (lo, hi):
            if nb and (max_ratio / max_ratio) <= med / nb <= max_ratio:
                too_far = False
                break
        if too_far and lo is not None and hi is not None:
            continue  # spike vs both neighbours — drop
        keep.append(p)
    return keep


def _load_history():
    """area -> {year: [prices]} for archive rents."""
    raw = json.loads((DATA / "area_individual_history_2016_2026.json").read_text())
    hist = defaultdict(lambda: defaultdict(list))
    for p in raw.get("prices", []):
        hist[f"{p['area'].strip()}|{p['city'].strip().lower()}"][p["year"]].append(float(p["price"]))
    return hist, raw.get("years_requested", [])


def _load_listings():
    rows = []
    with (DATA / "listings.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                price = float(r["price"])
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            r["_price"] = price
            r["_beds"] = _to_int(r.get("bedrooms"))
            r["_sqft"] = _to_float(r.get("area_sqft"))
            rows.append(r)
    return rows


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build():
    hist, years_requested = _load_history()
    listings = _load_listings()

    # Group listings by area|city, split rent/sale.
    by_area = defaultdict(lambda: {"rent": [], "sale": []})
    for r in listings:
        key = f"{(r.get('area') or '').strip()}|{(r.get('city') or '').strip().lower()}"
        if key.strip("|"):
            by_area[key][r["listing_type"]].append(r)

    areas = []
    for key, d in by_area.items():
        area_name, city = [p.strip() for p in key.split("|", 1)]
        if not area_name:
            continue
        hist_years = hist.get(key, {})

        # ---- growth from archive history (rent) ----
        # Some archived snapshots mix in sale-priced units (a 55k rent jumping
        # to 3.3M next year is a unit artifact, not appreciation). Filter any
        # point whose median is >4x or <1/4x of BOTH neighbours before trend
        # math, so CAGR reflects genuine rent movement.
        arch = []
        for y in sorted(hist_years):
            prices = hist_years[y]
            if prices:
                arch.append(
                    {
                        "year": y,
                        "median": round(statistics.median(prices), 0),
                        "n": len(prices),
                    }
                )
        arch = _despike(arch, max_ratio=4.0)
        cagr = total_change = None
        first_year = last_year = None
        if len(arch) >= 2:
            f, l = arch[0], arch[-1]
            first_year, last_year = f["year"], l["year"]
            if f["median"] and f["year"] != l["year"]:
                total_change = round((l["median"] / f["median"] - 1) * 100, 1)
                cagr = round(
                    ((l["median"] / f["median"]) ** (1 / (l["year"] - f["year"])) - 1) * 100, 1
                )
                # Real rent CAGR over a decade is realistically within +-30%/yr;
                # anything beyond is a residual artifact — flag and null it.
                if abs(cagr) > 40:
                    cagr = None
                    total_change = None

        # ---- current rent / sale aggregates ----
        med_rent = _med([r["_price"] for r in d["rent"]])
        med_sale = _med([r["_price"] for r in d["sale"]])
        med_rent_sqft = None
        rpft = [r["_price"] / r["_sqft"] for r in d["rent"] if r["_sqft"]]
        if rpft:
            med_rent_sqft = round(statistics.median(rpft), 0)
        spft = [r["_price"] / r["_sqft"] for r in d["sale"] if r["_sqft"]]
        med_sale_sqft = round(statistics.median(spft), 0) if spft else None

        gross_yield = round(med_rent / med_sale * 100, 1) if (med_rent and med_sale) else None

        areas.append(
            {
                "area": area_name,
                "city": city,
                "key": key,
                "rent_n": len(d["rent"]),
                "sale_n": len(d["sale"]),
                "med_rent_annual": round(med_rent) if med_rent else None,
                "med_sale": round(med_sale) if med_sale else None,
                "med_rent_sqft": med_rent_sqft,
                "med_sale_sqft": med_sale_sqft,
                "gross_yield_pct": gross_yield,
                "history": arch,
                "first_year": first_year,
                "last_year": last_year,
                "total_change_pct": total_change,
                "cagr_pct": cagr,
            }
        )

    areas.sort(key=lambda a: (a["city"], a["area"]))

    # ---- underpriced detection: current listings priced < 70% of area rent median ----
    underpriced = []
    for key, d in by_area.items():
        area_name, city = [p.strip() for p in key.split("|", 1)]
        med_rent = _med([r["_price"] for r in d["rent"]])
        if not med_rent:
            continue
        for r in d["rent"]:
            if r["_price"] < med_rent * 0.70 and r["_price"] > 0:
                underpriced.append(
                    {
                        "area": area_name,
                        "city": city,
                        "type": r.get("property_type", ""),
                        "beds": r["_beds"],
                        "price": r["_price"],
                        "area_median_rent": round(med_rent),
                        "discount_pct": round((1 - r["_price"] / med_rent) * 100, 1),
                        "url": r.get("url", ""),
                        "title": (r.get("title") or "")[:80],
                    }
                )
    underpriced.sort(key=lambda x: x["discount_pct"], reverse=True)

    # ---- top movers (fastest appreciation) ----
    movers = [a for a in areas if a["cagr_pct"] is not None]
    top_gainers = sorted(movers, key=lambda a: a["cagr_pct"], reverse=True)[:15]
    top_losers = sorted(movers, key=lambda a: a["cagr_pct"])[:15]

    # ---- yield ranking (rental investment) ----
    yielders = sorted(
        [a for a in areas if a["gross_yield_pct"] is not None and a["sale_n"] >= 2],
        key=lambda a: a["gross_yield_pct"],
        reverse=True,
    )

    # ---- affordability by bedrooms (sale) ----
    affordability = defaultdict(lambda: defaultdict(list))
    for r in listings:
        if r["listing_type"] != "sale" or r["_beds"] is None:
            continue
        a = (r.get("area") or "").strip()
        if a:
            affordability[a][r["_beds"]].append(r["_price"])
    aff_table = []
    for area, beds in affordability.items():
        row = {"area": area}
        for b, prices in beds.items():
            row[f"{b}br_median"] = round(statistics.median(prices))
            row[f"{b}br_n"] = len(prices)
        aff_table.append(row)

    n_rent = sum(1 for r in listings if r["listing_type"] == "rent")
    n_sale = sum(1 for r in listings if r["listing_type"] == "sale")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "All figures are AED asking prices (live PropertyFinder snapshot + archived "
            "Bayut rents). Gross yield = median annual rent / median sale price, before "
            "service charges, vacancy and fees. Directional only — not appraisals."
        ),
        "summary": {
            "listings_total": len(listings),
            "rent_listings": n_rent,
            "sale_listings": n_sale,
            "areas": len(areas),
            "areas_with_history": len(movers),
            "history_years": sorted({y for k in hist for y in hist[k]}),
            "years_requested": years_requested,
            "cities": sorted({a["city"] for a in areas}),
        },
        "areas": areas,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "yield_ranking": yielders[:20],
        "underpriced": underpriced[:25],
        "affordability": aff_table,
    }


def main():
    payload = build()
    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    js = "/* Auto-generated by tools/build_market_insights.py — do not edit. */\n"
    js += "window.MARKET_INSIGHTS = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    OUT_JS.write_text(js, encoding="utf-8")
    s = payload["summary"]
    print(f"Wrote {OUT_JS.relative_to(ROOT)}")
    print(f"  areas: {s['areas']} ({s['areas_with_history']} with growth history)")
    print(f"  listings: {s['listings_total']} (rent {s['rent_listings']} / sale {s['sale_listings']})")
    print(f"  underpriced flags: {len(payload['underpriced'])}  | yield-ranked: {len(payload['yield_ranking'])}")
    print(f"  top gainer: {payload['top_gainers'][0]['area']} ({payload['top_gainers'][0]['cagr_pct']}%/yr)" if payload["top_gainers"] else "")


if __name__ == "__main__":
    main()
