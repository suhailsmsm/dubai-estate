"""Unit tests for the mart source-precedence filter — the mechanism that
neutralizes cross-source duplicates (docs/DATADUBAI_REBUILD_PLAN.md §3).

Record-level cross-source matching is impossible for mortgages/gifts/rents,
so the aggregation resolves precedence by date instead:
    (data.dubai AND axis <= cutover) OR (gateway AND axis > cutover)
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from dxb import marts


def _session_with_cutover(dataset_map):
    session = MagicMock()
    session.get.side_effect = lambda model, key: dataset_map.get(key)
    return session


def test_precedence_clause_built_from_cutover_row():
    session = _session_with_cutover(
        {"transactions": SimpleNamespace(source_id=42, cutover_date=date(2026, 7, 20))}
    )

    clause, params = marts._precedence(session, "transactions", "f", "txn_date", "sale")

    # data.dubai rows are kept unconditionally; only the gateway is bounded
    assert "f.source_id = :src_sale" in clause
    assert "f.txn_date::date > :cut_sale" in clause
    assert params == {"src_sale": 42, "cut_sale": date(2026, 7, 20)}


def test_datadubai_rows_are_never_date_bounded():
    """An export is a complete snapshot as of its export date, so bounding
    data.dubai by the mart axis would drop legitimate rows — notably rent
    contracts that start after the export."""
    session = _session_with_cutover(
        {"rents": SimpleNamespace(source_id=7, cutover_date=date(2026, 7, 8))}
    )

    clause, _ = marts._precedence(session, "rents", "f", "registration_date", "rent")

    assert "f.source_id = :src_rent OR" in clause
    assert "<=" not in clause  # no upper bound applied to the data.dubai side


def test_rent_gateway_side_is_bounded_on_registration_not_start():
    """A lease is registered long before it starts; bounding the gateway on
    start_date would wrongly exclude contracts registered after the export
    that start sooner."""
    session = _session_with_cutover(
        {"rents": SimpleNamespace(source_id=7, cutover_date=date(2026, 7, 8))}
    )

    clause, _ = marts._precedence(session, "rents", "f", "registration_date", "rent")

    assert "f.registration_date::date > :cut_rent" in clause
    assert "start_date" not in clause


def test_no_cutover_means_no_filtering():
    """If data.dubai was never loaded the marts must aggregate everything
    rather than silently excluding all rows."""
    session = _session_with_cutover({})

    clause, params = marts._precedence(session, "rents", "f", "start_date", "rent")

    assert clause == ""
    assert params == {}


def test_rebuild_marts_injects_clauses_and_params(monkeypatch):
    session = _session_with_cutover(
        {
            "transactions": SimpleNamespace(
                source_id=1, cutover_date=date(2026, 7, 20)
            ),
            "rents": SimpleNamespace(source_id=2, cutover_date=date(2026, 7, 8)),
        }
    )
    session.execute.return_value.rowcount = 5

    report = marts.rebuild_marts(session)

    # 2 TRUNCATEs + 2 INSERTs
    assert session.execute.call_count == 4
    insert_calls = [c for c in session.execute.call_args_list if len(c[0]) > 1]
    assert len(insert_calls) == 2
    for call in insert_calls:
        sql = str(call[0][0])
        params = call[0][1]
        assert ":src_sale" in sql and ":src_rent" in sql
        assert params["src_sale"] == 1 and params["cut_sale"] == date(2026, 7, 20)
        assert params["src_rent"] == 2 and params["cut_rent"] == date(2026, 7, 8)
    assert report["cutover_applied"] == {"sales": True, "rents": True}


def test_rebuild_marts_without_cutovers_reports_not_applied(monkeypatch):
    session = _session_with_cutover({})
    session.execute.return_value.rowcount = 0

    report = marts.rebuild_marts(session)

    assert report["cutover_applied"] == {"sales": False, "rents": False}
    for call in session.execute.call_args_list:
        sql = str(call[0][0])
        assert ":src_sale" not in sql and ":src_rent" not in sql


def test_mart_sql_uses_start_date_for_rents_not_registration_date():
    for sql in (marts._AREA_MART_SQL, marts._PROJECT_MART_SQL):
        assert "date_trunc('month', f.start_date)" in sql
        assert "registration_date" not in sql
