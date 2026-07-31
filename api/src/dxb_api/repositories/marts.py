"""Monthly mart reads — multi-entity by design.

Shaped by the actual UX (API_DESIGN.md §7): the user ticks several areas or
projects in a multi-select, then pulls the whole selection in one request. So
these take *sets* of ids and report which of them produced no rows, rather
than silently dropping a series the user explicitly asked for.
"""

from __future__ import annotations

from datetime import date

from dxb_core.models import DimArea, DimProject, MartAreaMonthly, MartProjectMonthly
from sqlalchemy import Select, select

from dxb_api.repositories.base import BaseRepository


def _apply_area_geo(
    stmt: Select, has_geo_data: bool | None, geo_level: str | None
) -> Select:
    if geo_level == "polygon":
        return stmt.where(DimArea.boundary.isnot(None))
    if geo_level == "point":
        return stmt.where(DimArea.centroid.isnot(None))
    if has_geo_data is True:
        return stmt.where(
            (DimArea.centroid.isnot(None)) | (DimArea.boundary.isnot(None))
        )
    if has_geo_data is False:
        return stmt.where(DimArea.centroid.is_(None), DimArea.boundary.is_(None))
    return stmt


class MartRepository(BaseRepository):
    async def area_monthly(
        self,
        *,
        area_ids: list[int] | None = None,
        usage: str | None = None,
        month_from: date | None = None,
        month_to: date | None = None,
        min_sample: int | None = None,
        has_geo_data: bool | None = None,
        geo_level: str | None = None,
        include_future: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        area_ids = self._check_id_set(area_ids, "area_ids")
        limit, offset = self._bounded(limit, offset)
        m = MartAreaMonthly

        stmt = select(
            m.area_id.label("entity_id"),
            DimArea.name_en.label("name_en"),
            m.month,
            m.usage,
            m.sale_cnt,
            m.sale_median_price_m2,
            m.sale_p25_price_m2,
            m.sale_p75_price_m2,
            m.rent_cnt,
            m.rent_median_annual_m2,
            m.gross_yield_pct,
        ).join(DimArea, DimArea.id == m.area_id)

        stmt = _apply_area_geo(stmt, has_geo_data, geo_level)
        stmt = self._common_filters(
            stmt,
            m,
            area_ids,
            m.area_id,
            usage,
            month_from,
            month_to,
            min_sample,
            include_future,
        )
        stmt = stmt.order_by(DimArea.name_en.asc(), m.month.asc(), m.usage.asc())

        rows, has_more = await self._page(stmt, limit, offset)
        return await self._envelope(
            rows,
            area_ids,
            limit,
            offset,
            has_more,
            min_sample,
            include_future,
            stmt=stmt,
            id_col=m.area_id,
        )

    async def project_monthly(
        self,
        *,
        project_ids: list[int] | None = None,
        usage: str | None = None,
        month_from: date | None = None,
        month_to: date | None = None,
        min_sample: int | None = None,
        has_geo_data: bool | None = None,
        geo_level: str | None = None,
        include_future: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict:
        project_ids = self._check_id_set(project_ids, "project_ids")
        limit, offset = self._bounded(limit, offset)
        m = MartProjectMonthly

        stmt = select(
            m.project_id.label("entity_id"),
            DimProject.name_en.label("name_en"),
            m.month,
            m.usage,
            m.sale_cnt,
            m.sale_median_price_m2,
            m.sale_p25_price_m2,
            m.sale_p75_price_m2,
            m.rent_cnt,
            m.rent_median_annual_m2,
            m.gross_yield_pct,
        ).join(DimProject, DimProject.id == m.project_id)

        # Projects have points only, never polygons (see dimensions.py).
        if geo_level == "polygon":
            stmt = stmt.where(DimProject.id.is_(None))
        elif geo_level == "point" or has_geo_data is True:
            stmt = stmt.where(DimProject.location.isnot(None))
        elif has_geo_data is False:
            stmt = stmt.where(DimProject.location.is_(None))

        stmt = self._common_filters(
            stmt,
            m,
            project_ids,
            m.project_id,
            usage,
            month_from,
            month_to,
            min_sample,
            include_future,
        )
        stmt = stmt.order_by(DimProject.name_en.asc(), m.month.asc(), m.usage.asc())

        rows, has_more = await self._page(stmt, limit, offset)
        return await self._envelope(
            rows,
            project_ids,
            limit,
            offset,
            has_more,
            min_sample,
            include_future,
            stmt=stmt,
            id_col=m.project_id,
        )

    # ----------------------------------------------------------- helpers

    def _common_filters(
        self,
        stmt,
        m,
        ids,
        id_col,
        usage,
        month_from,
        month_to,
        min_sample,
        include_future,
    ):
        if ids:
            stmt = stmt.where(id_col.in_(ids))
        if usage:
            stmt = stmt.where(m.usage == usage)
        if month_from is not None:
            stmt = stmt.where(m.month >= month_from)
        if month_to is not None:
            stmt = stmt.where(m.month <= month_to)
        if not include_future:
            # Marts run to 2028 because rent contracts are start-dated years
            # ahead. Those months are real data but describe leases that have
            # not started, so they are opt-in rather than default.
            stmt = stmt.where(m.month <= date.today())
        if min_sample:
            # A month with one sale has a "median" that is just that sale.
            stmt = stmt.where((m.sale_cnt >= min_sample) | (m.rent_cnt >= min_sample))
        return stmt

    async def _ids_with_data(self, stmt, id_col) -> set[int]:
        """Which requested ids have *any* matching row, across the whole
        filtered set rather than just the current page.

        Deriving this from the page would be wrong in the ordinary case: the
        rows are ordered by name, so a selected entity whose rows fall past
        the page boundary would be reported as having no data at all. That is
        the exact false "no data" this reporting exists to prevent.
        """
        probe = stmt.with_only_columns(id_col).order_by(None).distinct()
        return {int(r[0]) for r in (await self._session.execute(probe)).all()}

    async def _envelope(
        self,
        rows,
        requested_ids,
        limit,
        offset,
        has_more,
        min_sample,
        include_future,
        stmt=None,
        id_col=None,
    ) -> dict:
        items = [dict(r._mapping) for r in rows]
        envelope = {
            "items": items,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "total": None,
            "applied": {
                "min_sample": min_sample,
                "include_future": include_future,
            },
        }
        if requested_ids:
            # Per-id reporting so a UI can flag "no data" against the exact
            # checkbox the user ticked, instead of quietly showing fewer
            # series than were selected.
            with_data = await self._ids_with_data(stmt, id_col)
            envelope["requested_ids"] = requested_ids
            envelope["returned_ids"] = sorted(set(requested_ids) & with_data)
            envelope["missing_ids"] = sorted(set(requested_ids) - with_data)
        return envelope
