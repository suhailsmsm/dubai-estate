from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from dxb_api.schemas.common import GeoFlags


class Area(GeoFlags):
    """A DLD community/area — the primary unit of geographic analysis."""

    id: int
    dld_area_code: str | None = Field(None, description="DLD code, e.g. 'A-292'.")
    name_en: str = Field(..., description="Canonical UPPER-cased English name.")
    name_ar: str | None = None
    zone_name: str | None = None
    geo_match_method: str | None = Field(
        None,
        description=(
            "How geometry was matched to this area: exact | parent_fallback | "
            "manual. parent_fallback means the shape belongs to a larger "
            "parent area, so it is approximate."
        ),
    )


class Project(GeoFlags):
    """A development project. Master projects contain sub-projects."""

    id: int
    dld_project_number: int | None = None
    name_en: str
    name_ar: str | None = None
    master_project_id: int | None = Field(
        None, description="Parent project id, when this is a sub-project."
    )
    master_project_en: str | None = None
    is_master: bool = Field(
        ...,
        description=(
            "True for master developments. The same name can exist as both a "
            "master and a regular project, so this disambiguates."
        ),
    )
    area_id: int | None = None
    developer_id: int | None = None
    status: str | None = None
    project_type: str | None = None
    percent_completed: Decimal | None = None
    cnt_units: int | None = None
    completion_date: date | None = None
    geo_match_method: str | None = Field(
        None,
        description=(
            "How `location` was placed. Precise: 'building_point' / "
            "'building_centroid' (Makani building rollup) and "
            "'master_of_children'; 'nominatim_validated' (OSM name match). "
            "Coarse: 'area_centroid', a fallback shared by every project in the "
            "area — do not render as precise. Null means no location yet."
        ),
    )
    geo_building_count: int | None = Field(
        None, description="Validated buildings behind a building-derived point."
    )
    geo_spread_m: Decimal | None = Field(
        None,
        description=(
            "Dispersion of those buildings (m). Large = big footprint; render "
            "an area label rather than a precise dot."
        ),
    )


class Building(BaseModel):
    """A building — the addressable unit that carries a precise location.

    `is_precise` is true only for a Makani-validated point; a building with
    `has_geo_data=false` is in the attribute register but not yet geocoded.
    """

    id: int
    name_en: str
    name_ar: str | None = None
    area_id: int | None = None
    area_name_en: str | None = None
    project_id: int | None = None
    project_name_en: str | None = None
    geo_match_method: str | None = Field(
        None, description="'makani_validated' for a precise point, else null."
    )
    is_precise: bool = Field(
        ..., description="True only for a Makani-validated location."
    )
    has_geo_data: bool
    # Physical attributes (data.dubai building register; may be null when the
    # building came only from a transaction and is not in the CSV register).
    built_up_area: Decimal | None = None
    floors: int | None = None
    flats: int | None = None
    offices: int | None = None
    shops: int | None = None
    car_parks: int | None = None
    elevators: int | None = None
    swimming_pools: int | None = None
    is_free_hold: bool | None = None
    rooms: str | None = Field(
        None, description="Villa-typical room count, e.g. '3 B/R'."
    )


class Developer(BaseModel):
    id: int
    dld_number: int | None = None
    name_en: str
    name_ar: str | None = None


class PropertyType(BaseModel):
    id: int
    usage: str
    prop_type: str
    prop_subtype: str | None = None


class Usage(BaseModel):
    """A raw `usage` value exactly as it appears in the data.

    Not normalized on purpose: the real values include Arabic text and near
    duplicates, and there is **no 'office' category**. Listing them is how a
    caller discovers the true vocabulary instead of inventing one.
    """

    usage: str
    property_type_count: int


class Source(BaseModel):
    id: int
    code: str
    name: str
    base_url: str
    license: str | None = None
    is_government: bool = Field(
        ...,
        description="True for verified government data; false for third-party mirrors.",
    )
