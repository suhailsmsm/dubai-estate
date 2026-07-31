from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from dxb_api.deps import DimensionRepoDep, MartRepoDep, PrincipalDep, csv_ints
from dxb_api.schemas.marts import MartPage

router = APIRouter(prefix="/marts", tags=["marts"])

GeoLevel = Literal["point", "polygon"]

_IDS = Query(
    description=(
        "Comma-separated ids, matching the multi-select UX: tick several "
        "entities, pull the whole selection in one request. Omit for all "
        "entities (subject to the page cap)."
    ),
)
_MIN_SAMPLE = Query(
    description=(
        "Drop months with fewer than this many transactions. Some months hold "
        "a single sale whose 'median' is just that sale."
    ),
)
_INCLUDE_FUTURE = Query(
    description=(
        "Include months after today. The marts extend to 2028 because leases "
        "are registered years ahead; those months are real but describe "
        "contracts that have not started."
    ),
)


@router.get(
    "/area-monthly",
    response_model=MartPage,
    summary="Monthly series for a set of areas",
)
async def area_monthly(
    repo: MartRepoDep,
    dims: DimensionRepoDep,
    _: PrincipalDep,
    area_ids: Annotated[str | None, _IDS] = None,
    q: Annotated[
        str | None,
        Query(description="Resolve one area by fuzzy name instead of passing ids."),
    ] = None,
    usage: str | None = None,
    month_from: date | None = None,
    month_to: date | None = None,
    min_sample: Annotated[int | None, _MIN_SAMPLE] = None,
    has_geo_data: bool | None = None,
    geo_level: GeoLevel | None = None,
    include_future: Annotated[bool, _INCLUDE_FUTURE] = False,
    limit: int | None = None,
    offset: int | None = None,
):
    ids = csv_ints(area_ids)
    resolved = None
    if q and not ids:
        area_id, resolved = await dims.resolve_area(q)
        ids = [area_id]
    result = await repo.area_monthly(
        area_ids=ids,
        usage=usage,
        month_from=month_from,
        month_to=month_to,
        min_sample=min_sample,
        has_geo_data=has_geo_data,
        geo_level=geo_level,
        include_future=include_future,
        limit=limit,
        offset=offset,
    )
    if resolved:
        result["resolved_entity"] = resolved
    return result


@router.get(
    "/project-monthly",
    response_model=MartPage,
    summary="Monthly series for a set of projects",
)
async def project_monthly(
    repo: MartRepoDep,
    dims: DimensionRepoDep,
    _: PrincipalDep,
    project_ids: Annotated[str | None, _IDS] = None,
    q: Annotated[
        str | None,
        Query(description="Resolve one project by fuzzy name instead of passing ids."),
    ] = None,
    area_id: Annotated[
        int | None, Query(description="Scopes `q=` resolution — project names repeat.")
    ] = None,
    usage: str | None = None,
    month_from: date | None = None,
    month_to: date | None = None,
    min_sample: Annotated[int | None, _MIN_SAMPLE] = None,
    has_geo_data: bool | None = None,
    geo_level: GeoLevel | None = None,
    include_future: Annotated[bool, _INCLUDE_FUTURE] = False,
    limit: int | None = None,
    offset: int | None = None,
):
    ids = csv_ints(project_ids)
    resolved = None
    if q and not ids:
        project_id, resolved = await dims.resolve_project(q, area_id=area_id)
        ids = [project_id]
    result = await repo.project_monthly(
        project_ids=ids,
        usage=usage,
        month_from=month_from,
        month_to=month_to,
        min_sample=min_sample,
        has_geo_data=has_geo_data,
        geo_level=geo_level,
        include_future=include_future,
        limit=limit,
        offset=offset,
    )
    if resolved:
        result["resolved_entity"] = resolved
    return result
