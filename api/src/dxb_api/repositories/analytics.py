"""Analytics: server-computed answers to the four question shapes.

These exist so an LLM makes **one** call and narrates a verified number,
instead of paging raw facts and doing the arithmetic itself — which is exactly
where it would hallucinate.

Division of labour: SQL fetches the monthly series (the marts are small —
86k area rows, 207k project rows — so this is cheap), and
`dxb_api.domain.metrics` computes the numbers in pure Python. That split is on
purpose: the arithmetic is the part most likely to be subtly wrong, and in
Python it is directly unit-testable without a database.
"""

from __future__ import annotations

from datetime import date

from dxb_core.models import DimArea, DimProject, MartAreaMonthly, MartProjectMonthly
from sqlalchemy import select

from dxb_api.domain import caveats, metrics
from dxb_api.errors import ValidationError
from dxb_api.repositories.base import BaseRepository

_METRICS = {
    "capital_growth": "capital_growth_cagr_pct",
    "gross_yield": "gross_rental_yield_pct",
    "total_return": "gross_total_return_pct",
    "sale_price_m2": "median_sale_aed_m2",
    "rent_m2": "median_rent_aed_m2_year",
}


class AnalyticsRepository(BaseRepository):
    # ------------------------------------------------------ series fetch

    async def _series(
        self,
        *,
        entity: str,
        ids: list[int] | None,
        usage: str | None,
        month_from: date | None,
        month_to: date | None,
        min_sample: int,
        has_geo_data: bool | None,
        geo_level: str | None,
    ) -> dict[int, dict]:
        """Monthly points per entity, keyed by id, with the entity name."""
        if entity == "area":
            m, dim, id_col = MartAreaMonthly, DimArea, MartAreaMonthly.area_id
        else:
            m, dim, id_col = (
                MartProjectMonthly,
                DimProject,
                MartProjectMonthly.project_id,
            )

        stmt = select(
            id_col.label("entity_id"),
            dim.name_en,
            m.month,
            m.sale_median_price_m2,
            m.sale_cnt,
            m.rent_median_annual_m2,
            m.rent_cnt,
        ).join(dim, dim.id == id_col)

        if entity == "area":
            if geo_level == "polygon":
                stmt = stmt.where(DimArea.boundary.isnot(None))
            elif geo_level == "point":
                stmt = stmt.where(DimArea.centroid.isnot(None))
            elif has_geo_data is True:
                stmt = stmt.where(
                    (DimArea.centroid.isnot(None)) | (DimArea.boundary.isnot(None))
                )
        elif geo_level == "point" or has_geo_data is True:
            stmt = stmt.where(DimProject.location.isnot(None))
        elif geo_level == "polygon":
            stmt = stmt.where(DimProject.id.is_(None))

        if ids:
            stmt = stmt.where(id_col.in_(ids))
        if usage:
            stmt = stmt.where(m.usage == usage)
        if month_from is not None:
            stmt = stmt.where(m.month >= month_from)
        if month_to is not None:
            stmt = stmt.where(m.month <= month_to)
        # Analytics never reach into future-dated months: annualizing a lease
        # that has not started is not a measurement of anything.
        stmt = stmt.where(m.month <= date.today())

        rows = (await self._session.execute(stmt)).all()

        out: dict[int, dict] = {}
        for r in rows:
            bucket = out.setdefault(
                r.entity_id, {"id": r.entity_id, "name_en": r.name_en, "points": []}
            )
            sale_ok = r.sale_cnt is not None and r.sale_cnt >= min_sample
            rent_ok = r.rent_cnt is not None and r.rent_cnt >= min_sample
            bucket["points"].append(
                metrics.MonthPoint(
                    month=r.month,
                    # Below min_sample the median is noise, so the value is
                    # dropped while the month itself is kept -- suppressing
                    # the number, not pretending the month never existed.
                    sale_median_price_m2=(
                        float(r.sale_median_price_m2)
                        if sale_ok and r.sale_median_price_m2 is not None
                        else None
                    ),
                    sale_cnt=int(r.sale_cnt or 0) if sale_ok else 0,
                    rent_median_annual_m2=(
                        float(r.rent_median_annual_m2)
                        if rent_ok and r.rent_median_annual_m2 is not None
                        else None
                    ),
                    rent_cnt=int(r.rent_cnt or 0) if rent_ok else 0,
                )
            )
        return out

    # ---------------------------------------------------------- ranking

    async def ranking(
        self,
        *,
        entity: str = "area",
        metric: str = "total_return",
        month_from: date | None = None,
        month_to: date | None = None,
        usage: str | None = None,
        min_sample: int | None = None,
        has_geo_data: bool | None = None,
        geo_level: str | None = None,
        limit: int = 25,
        ascending: bool = False,
    ) -> dict:
        if metric not in _METRICS:
            raise ValidationError(
                f"Unknown metric {metric!r}", allowed=sorted(_METRICS)
            )
        min_sample = (
            self._settings.default_min_sample if min_sample is None else min_sample
        )
        series = await self._series(
            entity=entity,
            ids=None,
            usage=usage,
            month_from=month_from,
            month_to=month_to,
            min_sample=min_sample,
            has_geo_data=has_geo_data,
            geo_level=geo_level,
        )

        key = _METRICS[metric]
        results = []
        for bucket in series.values():
            summary = metrics.summarize(bucket["points"])
            if summary.get(key) is None:
                continue  # not enough data to state this metric honestly
            results.append(
                {"id": bucket["id"], "name_en": bucket["name_en"], **summary}
            )

        results.sort(key=lambda r: r[key], reverse=not ascending)
        excluded = len(series) - len(results)
        return {
            "entity": entity,
            "metric": metric,
            "metric_field": key,
            "items": results[:limit],
            "applied": {
                "min_sample": min_sample,
                "month_from": month_from,
                "month_to": month_to,
                "usage": usage,
                "has_geo_data": has_geo_data,
                "geo_level": geo_level,
                "ascending": ascending,
            },
            "entities_considered": len(series),
            "entities_excluded_insufficient_data": excluded,
            **caveats.block(),
        }

    # ----------------------------------------------------------- growth

    async def growth(
        self,
        *,
        entity: str,
        entity_id: int,
        month_from: date | None = None,
        month_to: date | None = None,
        usage: str | None = None,
        min_sample: int | None = None,
        resolved: dict | None = None,
    ) -> dict:
        min_sample = (
            self._settings.default_min_sample if min_sample is None else min_sample
        )
        series = await self._series(
            entity=entity,
            ids=[entity_id],
            usage=usage,
            month_from=month_from,
            month_to=month_to,
            min_sample=min_sample,
            has_geo_data=None,
            geo_level=None,
        )
        bucket = series.get(entity_id)
        if bucket is None:
            return {
                "entity": entity,
                "id": entity_id,
                "name_en": None,
                "series": [],
                "yoy": [],
                "consecutive_yoy_increases": 0,
                "resolved_entity": resolved,
                "applied": {"min_sample": min_sample, "usage": usage},
                **caveats.block(["No mart rows matched these filters."]),
            }

        points = bucket["points"]
        steps = metrics.yoy_steps(points)
        summary = metrics.summarize(points)
        return {
            "entity": entity,
            "id": bucket["id"],
            "name_en": bucket["name_en"],
            **summary,
            "series": [
                {
                    "month": p.month,
                    "sale_median_price_m2": p.sale_median_price_m2,
                    "sale_cnt": p.sale_cnt,
                    "rent_median_annual_m2": p.rent_median_annual_m2,
                    "rent_cnt": p.rent_cnt,
                }
                for p in sorted(points, key=lambda p: p.month)
            ],
            "yoy": steps,
            "consecutive_yoy_increases": metrics.consecutive_yoy_increases(steps),
            "resolved_entity": resolved,
            "applied": {"min_sample": min_sample, "usage": usage},
            **caveats.block(),
        }

    # ------------------------------------------------------------ yield

    async def yields(
        self,
        *,
        entity: str = "area",
        month_from: date | None = None,
        month_to: date | None = None,
        usage: str | None = None,
        min_sample: int | None = None,
        has_geo_data: bool | None = None,
        geo_level: str | None = None,
        limit: int = 25,
        ascending: bool = False,
    ) -> dict:
        return await self.ranking(
            entity=entity,
            metric="gross_yield",
            month_from=month_from,
            month_to=month_to,
            usage=usage,
            min_sample=min_sample,
            has_geo_data=has_geo_data,
            geo_level=geo_level,
            limit=limit,
            ascending=ascending,
        )

    # ---------------------------------------------------------- compare

    async def compare(
        self,
        *,
        dimension: str,
        values: list[str],
        month_from: date | None = None,
        month_to: date | None = None,
        min_sample: int | None = None,
    ) -> dict:
        """Side-by-side metrics across usages or across named entities.

        `dimension=usage` is what answers "office vs residential" — note the
        data has no "office" usage at all, so the caller must first look at
        /dimensions/usages rather than assume the category exists.
        """
        min_sample = (
            self._settings.default_min_sample if min_sample is None else min_sample
        )
        if dimension not in ("usage", "area", "project"):
            raise ValidationError(
                f"Unknown dimension {dimension!r}", allowed=["usage", "area", "project"]
            )
        if not values:
            raise ValidationError(
                "compare requires at least one value", dimension=dimension
            )
        if len(values) > self._settings.max_entity_ids:
            raise ValidationError(
                f"compare accepts at most {self._settings.max_entity_ids} values",
                requested=len(values),
            )

        groups = []
        if dimension == "usage":
            for value in values:
                series = await self._series(
                    entity="area",
                    ids=None,
                    usage=value,
                    month_from=month_from,
                    month_to=month_to,
                    min_sample=min_sample,
                    has_geo_data=None,
                    geo_level=None,
                )
                # Pool every area's months for this usage into one series.
                pooled = [p for b in series.values() for p in b["points"]]
                groups.append(
                    {
                        "value": value,
                        "entities_pooled": len(series),
                        **metrics.summarize(pooled),
                    }
                )
        else:
            for value in values:
                entity_id, resolved = await self._resolve_named(dimension, value)
                series = await self._series(
                    entity=dimension,
                    ids=[entity_id],
                    usage=None,
                    month_from=month_from,
                    month_to=month_to,
                    min_sample=min_sample,
                    has_geo_data=None,
                    geo_level=None,
                )
                bucket = series.get(entity_id, {"name_en": None, "points": []})
                groups.append(
                    {
                        "value": value,
                        "id": entity_id,
                        "name_en": bucket.get("name_en"),
                        "resolved_entity": resolved,
                        **metrics.summarize(bucket["points"]),
                    }
                )

        return {
            "dimension": dimension,
            "groups": groups,
            "applied": {
                "min_sample": min_sample,
                "month_from": month_from,
                "month_to": month_to,
            },
            **caveats.block(),
        }

    async def _resolve_named(
        self, dimension: str, value: str
    ) -> tuple[int, dict | None]:
        if value.isdigit():
            return int(value), None
        from dxb_api.repositories.dimensions import DimensionRepository

        repo = DimensionRepository(self._session, self._settings)
        return await repo.resolve(dimension, value)
