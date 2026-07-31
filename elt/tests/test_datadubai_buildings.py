"""Unit tests for the data.dubai building-register importer mapping."""

from __future__ import annotations

from dxb.datadubai import buildings as bld


def _row(**kw):
    base = {
        "building_number": "LAKE TERRACE",
        "area_name_en": "Al Thanyah Fifth",
        "project_name_en": "LAKE TERRACE",
        "built_up_area": "237.19",
        "floors": "14",
        "flats": "120",
        "offices": "0",
        "shops": "2",
        "car_parks": "80",
        "elevators": "3",
        "swimming_pools": "1",
        "is_free_hold": "1",
        "rooms_en": "3 B/R",
    }
    base.update(kw)
    return base


_AREAS = {"AL THANYAH FIFTH": 55}
_PROJECTS = {"LAKE TERRACE": 700}


def test_row_maps_attributes_and_joins_project_by_name():
    v = bld._row_values(_row(), _AREAS, _PROJECTS)
    assert v["name_en"] == "LAKE TERRACE"
    assert v["area_id"] == 55
    assert v["project_id"] == 700
    assert v["built_up_area"] == 237.19
    assert v["floors"] == 14
    assert v["swimming_pools"] == 1
    assert v["is_free_hold"] is True
    assert v["rooms"] == "3 B/R"


def test_placeholder_code_zero_is_skipped():
    assert bld._row_values(_row(building_number="0"), _AREAS, _PROJECTS) is None


def test_blank_building_number_is_skipped():
    assert bld._row_values(_row(building_number=""), _AREAS, _PROJECTS) is None


def test_unknown_area_drops_the_row():
    assert bld._row_values(_row(area_name_en="Nowhere"), _AREAS, _PROJECTS) is None


def test_unmatched_project_leaves_project_id_null_but_keeps_row():
    v = bld._row_values(_row(project_name_en="Ghost Project"), _AREAS, _PROJECTS)
    assert v is not None
    assert v["project_id"] is None


def test_freehold_zero_is_false_and_missing_is_none():
    assert (
        bld._row_values(_row(is_free_hold="0"), _AREAS, _PROJECTS)["is_free_hold"]
        is False
    )
    assert (
        bld._row_values(_row(is_free_hold=""), _AREAS, _PROJECTS)["is_free_hold"]
        is None
    )


def test_update_cols_never_touch_geolocation():
    """The CSV enrichment fills attributes only; Makani owns location/method."""
    for forbidden in ("location", "geo_match_method", "geo_source_id", "makani"):
        assert forbidden not in bld._UPDATE_COLS


def test_dedupe_collapses_duplicate_conflict_keys_last_wins():
    """A building_number repeats across property rows; ON CONFLICT rejects the
    same key twice in one statement, so a batch must be deduped first."""
    batch = [
        {"name_en": "Q1", "area_id": 5, "floors": 10},
        {"name_en": "Q1", "area_id": 5, "floors": 12},  # dup key, later wins
        {"name_en": "Q1", "area_id": 6, "floors": 3},  # different area, kept
    ]
    out = bld._dedupe(batch)
    assert len(out) == 2
    q1_area5 = next(r for r in out if r["area_id"] == 5)
    assert q1_area5["floors"] == 12
