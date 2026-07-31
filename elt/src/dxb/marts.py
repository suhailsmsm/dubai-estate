"""Analytics marts: wholesale rebuild after each load (fast at this scale).

Medians via percentile_cont; Sales only (mortgages/gifts are price outliers);
per-m2 values clamped to a sane range to keep data-entry glitches out of the
aggregates.

Source precedence (docs/DATADUBAI_REBUILD_PLAN.md §3): where two sources
overlap in time, the aggregation — not the fact table — picks the winner:

    data.dubai row  -> always kept (an export is a complete snapshot)
    gateway row     -> kept only past the cutover, where it stops duplicating

Raw facts keep everything from both sources; only the mart deduplicates. This
is why no cross-source record matching is needed (it is impossible for
mortgages/gifts/rents) and why the gateway's 2-day overlap is harmless.
Rebuilding wholesale means moving a cutover re-segregates everything.

The gateway side is compared on the column expressing *its* boundary —
txn_date for sales, registration_date for rents — because a lease is
registered long before it starts. The reporting month is a separate axis:
txn_date for sales, start_date for rents (both populated by both sources).
"""

from __future__ import annotations

import logging

from dxb_core.models import EtlSourceCutover
from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def _precedence(
    session: Session, dataset: str, alias: str, gateway_axis: str, tag: str
):
    """SQL fragment + params applying source precedence for one dataset.

    data.dubai rows are always kept — an export is a complete authoritative
    snapshot as of its export date. Other sources (the gateway) are kept only
    past the cutover, which is where their rows stop being duplicates.

    `gateway_axis` is the column that expresses *that source's* boundary:
      transactions -> txn_date          (transaction date ~ registration date)
      rents        -> registration_date (start_date would be the wrong axis:
                      leases start long after they are registered)

    No cutover configured (data.dubai never loaded) -> no filtering.
    """
    row = session.get(EtlSourceCutover, dataset)
    if row is None:
        return "", {}
    clause = (
        f" AND ({alias}.source_id = :src_{tag}"
        f" OR {alias}.{gateway_axis}::date > :cut_{tag})"
    )
    return clause, {f"src_{tag}": row.source_id, f"cut_{tag}": row.cutover_date}


_AREA_MART_SQL = """
INSERT INTO mart_area_monthly (
    area_id, month, usage, sale_cnt, sale_median_price_m2, sale_p25_price_m2,
    sale_p75_price_m2, rent_cnt, rent_median_annual_m2, gross_yield_pct
)
SELECT
    coalesce(s.area_id, r.area_id),
    coalesce(s.month, r.month),
    coalesce(s.usage, r.usage),
    s.cnt,
    s.med, s.p25, s.p75,
    r.cnt,
    r.med,
    round((r.med / nullif(s.med, 0) * 100)::numeric, 2)
FROM (
    SELECT f.area_id,
           date_trunc('month', f.txn_date)::date AS month,
           coalesce(pt.usage, 'Unknown') AS usage,
           count(*)::int AS cnt,
           round((percentile_cont(0.5)
                  WITHIN GROUP (ORDER BY f.price_per_m2))::numeric, 2) AS med,
           round((percentile_cont(0.25)
                  WITHIN GROUP (ORDER BY f.price_per_m2))::numeric, 2) AS p25,
           round((percentile_cont(0.75)
                  WITHIN GROUP (ORDER BY f.price_per_m2))::numeric, 2) AS p75
    FROM fact_sale_transaction f
    LEFT JOIN dim_property_type pt ON pt.id = f.property_type_id
    WHERE f.txn_group = 'Sales' AND f.price_per_m2 BETWEEN 500 AND 200000
      AND f.txn_date >= DATE '1990-01-01'{sale_prec}
    GROUP BY 1, 2, 3
) s
FULL OUTER JOIN (
    SELECT f.area_id,
           date_trunc('month', f.start_date)::date AS month,
           coalesce(pt.usage, 'Unknown') AS usage,
           count(*)::int AS cnt,
           round((percentile_cont(0.5)
                  WITHIN GROUP (ORDER BY f.rent_per_m2_year))::numeric, 2) AS med
    FROM fact_rent_contract f
    LEFT JOIN dim_property_type pt ON pt.id = f.property_type_id
    WHERE f.rent_per_m2_year BETWEEN 50 AND 20000
      AND f.start_date IS NOT NULL
      AND f.start_date <= CURRENT_DATE + INTERVAL '2 years'{rent_prec}
    GROUP BY 1, 2, 3
) r USING (area_id, month, usage)
"""

_PROJECT_MART_SQL = """
INSERT INTO mart_project_monthly (
    project_id, month, usage, sale_cnt, sale_median_price_m2, sale_p25_price_m2,
    sale_p75_price_m2, rent_cnt, rent_median_annual_m2, gross_yield_pct
)
SELECT
    coalesce(s.project_id, r.project_id),
    coalesce(s.month, r.month),
    coalesce(s.usage, r.usage),
    s.cnt,
    s.med, s.p25, s.p75,
    r.cnt,
    r.med,
    round((r.med / nullif(s.med, 0) * 100)::numeric, 2)
FROM (
    SELECT f.project_id,
           date_trunc('month', f.txn_date)::date AS month,
           coalesce(pt.usage, 'Unknown') AS usage,
           count(*)::int AS cnt,
           round((percentile_cont(0.5)
                  WITHIN GROUP (ORDER BY f.price_per_m2))::numeric, 2) AS med,
           round((percentile_cont(0.25)
                  WITHIN GROUP (ORDER BY f.price_per_m2))::numeric, 2) AS p25,
           round((percentile_cont(0.75)
                  WITHIN GROUP (ORDER BY f.price_per_m2))::numeric, 2) AS p75
    FROM fact_sale_transaction f
    LEFT JOIN dim_property_type pt ON pt.id = f.property_type_id
    WHERE f.project_id IS NOT NULL
      AND f.txn_group = 'Sales' AND f.price_per_m2 BETWEEN 500 AND 200000
      AND f.txn_date >= DATE '1990-01-01'{sale_prec}
    GROUP BY 1, 2, 3
) s
FULL OUTER JOIN (
    SELECT f.project_id,
           date_trunc('month', f.start_date)::date AS month,
           coalesce(pt.usage, 'Unknown') AS usage,
           count(*)::int AS cnt,
           round((percentile_cont(0.5)
                  WITHIN GROUP (ORDER BY f.rent_per_m2_year))::numeric, 2) AS med
    FROM fact_rent_contract f
    LEFT JOIN dim_property_type pt ON pt.id = f.property_type_id
    WHERE f.project_id IS NOT NULL AND f.rent_per_m2_year BETWEEN 50 AND 20000
      AND f.start_date IS NOT NULL
      AND f.start_date <= CURRENT_DATE + INTERVAL '2 years'{rent_prec}
    GROUP BY 1, 2, 3
) r USING (project_id, month, usage)
"""


def rebuild_marts(session: Session) -> dict:
    sale_prec, sale_params = _precedence(
        session, "transactions", "f", "txn_date", "sale"
    )
    rent_prec, rent_params = _precedence(
        session, "rents", "f", "registration_date", "rent"
    )
    params = {**sale_params, **rent_params}

    session.execute(text("TRUNCATE mart_area_monthly"))
    area_rows = session.execute(
        text(_AREA_MART_SQL.format(sale_prec=sale_prec, rent_prec=rent_prec)), params
    ).rowcount
    session.execute(text("TRUNCATE mart_project_monthly"))
    project_rows = session.execute(
        text(_PROJECT_MART_SQL.format(sale_prec=sale_prec, rent_prec=rent_prec)), params
    ).rowcount
    session.commit()
    log.info(
        "marts rebuilt: area=%s project=%s (cutovers applied: sales=%s rents=%s)",
        area_rows,
        project_rows,
        bool(sale_prec),
        bool(rent_prec),
    )
    return {
        "mart_area_monthly": area_rows,
        "mart_project_monthly": project_rows,
        "cutover_applied": {"sales": bool(sale_prec), "rents": bool(rent_prec)},
    }
