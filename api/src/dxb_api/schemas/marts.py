from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class MartRow(BaseModel):
    """One (entity, month, usage) cell of the monthly time series.

    Always read `sale_cnt` / `rent_cnt` before trusting a median: some months
    contain a single transaction, and its "median" is just that one price.
    """

    entity_id: int
    name_en: str
    month: date = Field(..., description="First day of the month.")
    usage: str
    sale_cnt: int | None = Field(None, description="Sales behind the sale medians.")
    sale_median_price_m2: Decimal | None = None
    sale_p25_price_m2: Decimal | None = None
    sale_p75_price_m2: Decimal | None = Field(
        None, description="With p25, the spread — a wide band means a mixed month."
    )
    rent_cnt: int | None = Field(None, description="Contracts behind the rent median.")
    rent_median_annual_m2: Decimal | None = None
    gross_yield_pct: Decimal | None = Field(
        None, description="rent_median_annual_m2 / sale_median_price_m2, gross."
    )


class MartApplied(BaseModel):
    min_sample: int | None = None
    include_future: bool = False


class MartPage(BaseModel):
    items: list[MartRow]
    limit: int
    offset: int
    has_more: bool
    total: int | None = None
    applied: MartApplied
    requested_ids: list[int] | None = Field(
        None, description="The ids asked for, echoed back."
    )
    returned_ids: list[int] | None = Field(
        None, description="Ids that actually produced rows."
    )
    missing_ids: list[int] | None = Field(
        None,
        description=(
            "Requested ids with no matching mart rows. Surface these as "
            "'no data' per selection rather than dropping the series."
        ),
    )
