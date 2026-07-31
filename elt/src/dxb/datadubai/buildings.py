"""Ingest the data.dubai building register into dim_building (attributes).

This is enrichment, not facts. Each CSV row is a building identified by a
`building_number` **code** (e.g. 'RM2 Mira Oasis II-V-232'), not a searchable
name — so these rows form an *attributed register* keyed by (code, area),
distinct from the name-keyed, geocodable buildings that the transaction
transform creates. Merging the two populations is a documented open point
(docs/PROJECT_GEO_ENRICHMENT.md §6 / BUILDING_CSV_ANALYSIS.md); until then the
Makani geocoder only targets fact-referenced (transaction) buildings, so these
code-named rows are never geocoded and carry attributes only.

Re-runnable: guarded upsert on (name_en, area_id), so re-importing a fresh
monthly export tops up changed attributes without duplicating rows. This is the
same recurring model as the transaction/rent import, and shares its CLI entry
point (`dxb import-datadubai buildings`).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from dxb_core.models import DimArea, DimBuilding, DimProject
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from dxb.datadubai.sources import DATASETS, files_for
from dxb.transform.dld import norm_name, to_float, to_int, to_text

log = logging.getLogger(__name__)

csv.field_size_limit(10_000_000)

BATCH = 2000

# Columns refreshed on conflict — the enrichable attributes only (never the
# geolocation columns, which Makani owns).
_UPDATE_COLS = (
    "name_ar",
    "project_id",
    "built_up_area",
    "floors",
    "flats",
    "offices",
    "shops",
    "car_parks",
    "elevators",
    "swimming_pools",
    "is_free_hold",
    "rooms",
)


def _row_values(row: dict, areas: dict, projects: dict) -> dict | None:
    name = norm_name(row.get("building_number"))
    # '0' and blanks are placeholder codes, not buildings.
    if not name or name == "0":
        return None
    area_id = areas.get(norm_name(row.get("area_name_en")))
    if area_id is None:
        return None
    free = to_text(row.get("is_free_hold"))
    return {
        "name_en": name,
        "name_ar": None,
        "area_id": area_id,
        "project_id": projects.get(norm_name(row.get("project_name_en"))),
        "built_up_area": to_float(row.get("built_up_area")),
        "floors": to_int(row.get("floors")),
        "flats": to_int(row.get("flats")),
        "offices": to_int(row.get("offices")),
        "shops": to_int(row.get("shops")),
        "car_parks": to_int(row.get("car_parks")),
        "elevators": to_int(row.get("elevators")),
        "swimming_pools": to_int(row.get("swimming_pools")),
        "is_free_hold": (free == "1") if free is not None else None,
        "rooms": to_text(row.get("rooms_en")),
    }


def _dedupe(batch: list[dict]) -> list[dict]:
    """Collapse duplicate (name_en, area_id) rows, keeping the last.

    A building_number repeats across CSV rows (multiple registered properties
    in one building), so a single batch can propose the same conflict key more
    than once — which ON CONFLICT DO UPDATE rejects with a CardinalityViolation.
    Last-wins is fine here: the attributes are building-level, identical across
    a building's property rows.
    """
    collapsed: dict[tuple, dict] = {}
    for row in batch:
        collapsed[(row["name_en"], row["area_id"])] = row
    return list(collapsed.values())


def _flush(session: Session, batch: list[dict]) -> int:
    if not batch:
        return 0
    stmt = pg_insert(DimBuilding.__table__).values(_dedupe(batch))
    stmt = stmt.on_conflict_do_update(
        constraint="ux_building_name_area",
        set_={c: stmt.excluded[c] for c in _UPDATE_COLS},
    ).returning(DimBuilding.id)
    n = len(session.execute(stmt).fetchall())
    session.commit()
    return n


def import_buildings(session: Session, source_url: str | None = None) -> dict:
    """Stream the buildings CSVs into dim_building attribute rows."""
    files = files_for(DATASETS["buildings"])
    if not files:
        raise FileNotFoundError(
            "no files matching buildings_*.csv under data/raw — "
            "see docs/BUILDING_CSV_ANALYSIS.md"
        )

    # Name -> id lookups (dims are small). Projects are matched by name only
    # (regular projects), the reliable key per BUILDING_CSV_ANALYSIS.
    areas = {n: i for n, i in session.execute(select(DimArea.name_en, DimArea.id))}
    projects = {
        n: i
        for n, i, m in session.execute(
            select(DimProject.name_en, DimProject.id, DimProject.is_master)
        )
        if not m
    }

    report = {"read": 0, "written": 0, "skipped": 0, "files": []}
    for path in files:
        read = written = skipped = 0
        batch: list[dict] = []
        with open(Path(path), encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                read += 1
                values = _row_values(row, areas, projects)
                if values is None:
                    skipped += 1
                    continue
                batch.append(values)
                if len(batch) >= BATCH:
                    written += _flush(session, batch)
                    batch.clear()
            written += _flush(session, batch)
        log.info("%s: read=%s written=%s skipped=%s", path.name, read, written, skipped)
        report["files"].append({"file": path.name, "read": read, "written": written})
        report["read"] += read
        report["written"] += written
        report["skipped"] += skipped

    log.info(
        "buildings import complete: read=%s written=%s skipped=%s",
        report["read"],
        report["written"],
        report["skipped"],
    )
    return report
