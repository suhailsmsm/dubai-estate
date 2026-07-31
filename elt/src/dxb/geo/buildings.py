"""Building geolocation via Makani, then rollup into project locations.

Two stages (docs/PROJECT_GEO_ENRICHMENT.md §6):

  enrich_buildings          : geocode each building via Makani, accept the point
                              only if it falls inside the building's DLD area
                              (containment validation — 0 false positives).
  place_projects_from_buildings : derive each project's point from its validated
                              buildings using the outlier-robust geometric
                              median, with confidence columns and a master-
                              project hierarchy.

Everything here is synchronous (ELT), non-fatal at the hook level, and only
ever *upgrades* precision — a building/project already precisely placed is not
recomputed downward.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from dxb.db.engine import source_id
from dxb.geo.makani import MakaniClient, pick_candidate

log = logging.getLogger(__name__)

# A validated point must fall inside the area polygon, or within this many
# metres of the area centroid when no boundary exists. Same bound as the OSM
# path (osm_geo/projects.py).
_CENTROID_RADIUS_M = 3000


# ------------------------------------------------------------ building geocode


def enrich_buildings(
    session: Session, missing_only: bool = True, limit: int | None = None
) -> dict:
    """Geocode buildings via Makani and set a validated `location`.

    `missing_only=True` (the pipeline hook) only touches buildings never
    geocoded yet (`geo_match_method IS NULL`); `False` (the full CLI sweep)
    reconsiders everything not already `makani_validated`. Only buildings whose
    area has a centroid are attempted — without one there is nothing to
    validate against.
    """
    method_filter = (
        "b.geo_match_method IS NULL"
        if missing_only
        else "b.geo_match_method IS DISTINCT FROM 'makani_validated'"
    )
    rows = session.execute(
        text(
            f"""
            SELECT b.id, b.name_en, a.name_en AS area_name, a.id AS area_id
            FROM dim_building b
            JOIN dim_area a ON a.id = b.area_id
            WHERE a.centroid IS NOT NULL AND {method_filter}
              -- Only geocode buildings that appear in transactions: those carry
              -- a real searchable name. The CSV attribute register uses opaque
              -- building_number codes that Makani cannot resolve, so skip them
              -- rather than burn throttled calls on guaranteed misses.
              AND EXISTS (
                  SELECT 1 FROM fact_sale_transaction f WHERE f.building_id = b.id
              )
            ORDER BY b.id
            """
        )
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]

    sid = source_id(session, "makani")
    report = {"attempted": 0, "validated": 0, "no_result": 0, "outside_area": 0}
    if not rows:
        return report

    with MakaniClient() as client:
        for row in rows:
            report["attempted"] += 1
            query = f"{row.name_en}, {row.area_name}, Dubai"
            try:
                candidates = client.find_place(query)
            except Exception:
                log.exception("makani query failed for building %s", row.name_en)
                continue
            cand = pick_candidate(candidates)
            if cand is None:
                report["no_result"] += 1
                continue
            loc = cand["geometry"]["location"]
            lat, lng = float(loc["lat"]), float(loc["lng"])
            if not _in_area(session, row.area_id, lat, lng):
                report["outside_area"] += 1
                continue
            session.execute(
                text(
                    """
                    UPDATE dim_building
                    SET location = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                        geo_source_id = :sid,
                        geo_match_method = 'makani_validated',
                        makani = :makani,
                        updated_at = now()
                    WHERE id = :bid
                    """
                ),
                {
                    "lng": lng,
                    "lat": lat,
                    "sid": sid,
                    "makani": (cand.get("name") or "")[:255] or None,
                    "bid": row.id,
                },
            )
            session.commit()
            report["validated"] += 1

    log.info(
        "building geo: attempted=%s validated=%s no_result=%s outside_area=%s",
        report["attempted"],
        report["validated"],
        report["no_result"],
        report["outside_area"],
    )
    return report


def _in_area(session: Session, area_id: int, lat: float, lng: float) -> bool:
    chk = session.execute(
        text(
            """
            SELECT coalesce(ST_Contains(boundary::geometry,
                     ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)), false)
                 OR ST_DWithin(centroid,
                     ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :r)
            FROM dim_area WHERE id = :aid
            """
        ),
        {"lng": lng, "lat": lat, "aid": area_id, "r": _CENTROID_RADIUS_M},
    ).scalar()
    return bool(chk)


# ---------------------------------------------------- project rollup (median)

# Per-project: geometric median of validated building points (outlier-robust,
# unlike the mean centroid), the 90th-percentile spread from it, and whether it
# lands inside the project's area. ST_GeometricMedian handles the 1-point case
# by returning that point.
_PROJECT_AGG_SQL = """
WITH pts AS (
    SELECT b.location::geometry AS g, b.location AS geog
    FROM dim_building b
    WHERE b.project_id = :pid
      AND b.geo_match_method = 'makani_validated'
      AND b.location IS NOT NULL
),
med AS (
    SELECT ST_GeometricMedian(ST_Collect(g)) AS m, count(*) AS n FROM pts
)
SELECT med.n AS n,
       ST_Y(med.m) AS lat,
       ST_X(med.m) AS lng,
       coalesce((SELECT percentile_cont(0.9) WITHIN GROUP (
                    ORDER BY ST_Distance(pts.geog, med.m::geography))
                 FROM pts), 0) AS spread_m,
       (SELECT coalesce(ST_Contains(a.boundary::geometry, med.m), false)
             OR ST_DWithin(a.centroid, med.m::geography, :r)
        FROM dim_area a WHERE a.id = :area_id) AS in_area
FROM med
WHERE med.m IS NOT NULL
"""

# Master projects: median of their child projects' *precise* points.
_MASTER_AGG_SQL = """
WITH pts AS (
    SELECT p.location::geometry AS g
    FROM dim_project p
    WHERE p.master_project_id = :mid
      AND p.location IS NOT NULL
      AND p.geo_match_method IN ('building_point', 'building_centroid')
),
med AS (SELECT ST_GeometricMedian(ST_Collect(g)) AS m, count(*) AS n FROM pts)
SELECT med.n AS n, ST_Y(med.m) AS lat, ST_X(med.m) AS lng
FROM med WHERE med.m IS NOT NULL
"""


def place_projects_from_buildings(session: Session) -> dict:
    """Set project locations from their validated buildings.

    Regular projects: geometric median of their buildings, validated inside the
    project's area (else left for the area-centroid fallback). Master projects:
    geometric median of their precisely-placed child projects. Recomputed
    wholesale — a derived value, like the marts.
    """
    report = {
        "building_point": 0,
        "building_centroid": 0,
        "master_of_children": 0,
        "rejected_outside_area": 0,
    }
    sid = source_id(session, "makani")

    regular = session.execute(
        text(
            """
            SELECT DISTINCT p.id, p.area_id
            FROM dim_project p
            JOIN dim_building b ON b.project_id = p.id
            WHERE p.is_master = false
              AND b.geo_match_method = 'makani_validated'
            """
        )
    ).fetchall()

    for proj in regular:
        agg = session.execute(
            text(_PROJECT_AGG_SQL),
            {"pid": proj.id, "area_id": proj.area_id, "r": _CENTROID_RADIUS_M},
        ).first()
        if agg is None or agg.lat is None:
            continue
        if not agg.in_area:
            report["rejected_outside_area"] += 1
            continue
        method = "building_point" if agg.n == 1 else "building_centroid"
        _set_project_point(
            session, proj.id, agg.lat, agg.lng, sid, method, agg.n, agg.spread_m
        )
        report[method] += 1

    # Masters after regulars, so children are already placed.
    masters = session.execute(
        text("SELECT id FROM dim_project WHERE is_master = true")
    ).fetchall()
    for m in masters:
        agg = session.execute(text(_MASTER_AGG_SQL), {"mid": m.id}).first()
        if agg is None or agg.lat is None:
            continue
        _set_project_point(
            session, m.id, agg.lat, agg.lng, sid, "master_of_children", agg.n, None
        )
        report["master_of_children"] += 1

    session.commit()
    log.info(
        "project placement from buildings: point=%s centroid=%s master=%s rejected=%s",
        report["building_point"],
        report["building_centroid"],
        report["master_of_children"],
        report["rejected_outside_area"],
    )
    return report


def _set_project_point(session, pid, lat, lng, sid, method, n, spread_m) -> None:
    session.execute(
        text(
            """
            UPDATE dim_project
            SET location = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                geo_source_id = :sid,
                geo_match_method = :method,
                geo_building_count = :n,
                geo_spread_m = :spread,
                updated_at = now()
            WHERE id = :pid
            """
        ),
        {
            "lng": lng,
            "lat": lat,
            "sid": sid,
            "method": method,
            "n": n,
            "spread": round(float(spread_m), 1) if spread_m is not None else None,
            "pid": pid,
        },
    )


# ------------------------------------------------------------- non-fatal hook


def enrich_missing_building_geo(session: Session) -> dict:
    """Pipeline hook: geocode newly-seen buildings, then re-roll projects.
    Never raises — a Makani outage must not fail the data-collection run."""
    try:
        buildings = enrich_buildings(session, missing_only=True)
        projects = place_projects_from_buildings(session)
        return {"buildings": buildings, "projects": projects}
    except Exception:
        log.exception("building geo enrichment failed — continuing without it")
        return {"error": True}
