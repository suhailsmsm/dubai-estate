"""Shared repository machinery: pagination and fuzzy entity resolution.

The only layer permitted to import SQLAlchemy (API_DESIGN.md §3, enforced by
the ruff TID251 ban configured in pyproject.toml).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dxb_api.config import Settings
from dxb_api.errors import AmbiguousEntityError, ValidationError


@dataclass(frozen=True)
class Candidate:
    id: int
    name_en: str
    similarity: float


class BaseRepository:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    # ------------------------------------------------------------ paging

    def _bounded(self, limit: int | None, offset: int | None) -> tuple[int, int]:
        limit = self._settings.default_page_limit if limit is None else limit
        offset = offset or 0
        if limit < 1 or limit > self._settings.max_page_limit:
            raise ValidationError(
                f"limit must be between 1 and {self._settings.max_page_limit}",
                limit=limit,
            )
        if offset < 0:
            raise ValidationError("offset must be >= 0", offset=offset)
        return limit, offset

    async def _page(self, stmt: Select, limit: int, offset: int) -> tuple[list, bool]:
        """Fetch one page plus a sentinel row.

        Asking for limit+1 rows tells us whether more exist without a second
        COUNT query over the same predicate — which on the 12M-row fact tables
        would roughly double the cost of every page.
        """
        rows = (await self._session.execute(stmt.limit(limit + 1).offset(offset))).all()
        return list(rows[:limit]), len(rows) > limit

    async def _count(self, stmt: Select) -> int:
        subq = stmt.order_by(None).subquery()
        return int(
            await self._session.scalar(select(func.count()).select_from(subq)) or 0
        )

    def _check_id_set(self, ids: list[int] | None, param: str) -> list[int] | None:
        if not ids:
            return None
        if len(ids) > self._settings.max_entity_ids:
            raise ValidationError(
                f"{param} accepts at most {self._settings.max_entity_ids} ids; "
                "narrow the selection rather than requesting everything.",
                requested=len(ids),
                max_entity_ids=self._settings.max_entity_ids,
            )
        return ids

    # -------------------------------------------------- fuzzy resolution

    async def _resolve(
        self,
        *,
        query: str,
        name_col,
        id_col,
        base_stmt: Select,
        entity: str,
    ) -> tuple[int, dict]:
        """Turn a `q=` string into exactly one id, or raise 422.

        `similarity()` is used directly with an explicit threshold rather than
        the `%` operator, because `%` consults the session-level
        pg_trgm.similarity_threshold — a hidden global that would make results
        depend on connection state instead of on the request.
        """
        threshold = self._settings.trgm_threshold
        sim = func.similarity(name_col, query).label("sim")
        stmt = (
            base_stmt.add_columns(sim)
            .where(sim >= threshold)
            .order_by(sim.desc(), name_col.asc())
            .limit(5)
        )
        rows = (await self._session.execute(stmt)).all()
        candidates = [
            Candidate(
                id=int(r._mapping[id_col]),
                name_en=r._mapping[name_col],
                similarity=float(r.sim),
            )
            for r in rows
        ]

        if not candidates:
            raise AmbiguousEntityError(
                f"No {entity} matched {query!r} above a similarity of {threshold}.",
                query=query,
                candidates=[],
                hint=(
                    "Trigram matching is lexical, so acronyms and nicknames "
                    "(e.g. 'JVC') do not match. Try the full name, or list the "
                    "dimension endpoint to see the real values."
                ),
            )

        best = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        if (
            runner_up
            and (best.similarity - runner_up.similarity)
            < self._settings.trgm_ambiguity_margin
        ):
            # Guessing here is the hallucination vector: correct arithmetic
            # attached to the wrong entity reads as authoritative.
            raise AmbiguousEntityError(
                f"{query!r} matches more than one {entity} about equally well. "
                "Pass an explicit id, or narrow the query.",
                query=query,
                candidates=[c.__dict__ for c in candidates],
            )

        resolved = {
            "query": query,
            "id": best.id,
            "name_en": best.name_en,
            "similarity": round(best.similarity, 3),
            "runners_up": [c.__dict__ for c in candidates[1:]],
        }
        return best.id, resolved
