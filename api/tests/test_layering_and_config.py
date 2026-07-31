"""Architectural invariants and settings parsing.

The layering tests are deliberately mechanical: the ruff TID251 ban catches
these at commit time, but only if someone runs the hook. These fail the build.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from dxb_api.config import build_settings

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "dxb_api"
BANNED = ("sqlalchemy", "dxb_core", "geoalchemy2")


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_only_repositories_touch_sqlalchemy_or_the_shared_schema():
    """A router that cannot import SQLAlchemy cannot accidentally query."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if "repositories" in path.parts:
            continue
        leaked = _imports(path) & set(BANNED)
        if leaked:
            offenders.append(f"{path.relative_to(SRC)} imports {sorted(leaked)}")
    assert offenders == []


def test_api_never_imports_the_elt_package():
    """They share only dxb-core; importing elt would put write code one import
    away from a service that must never write (CLAUDE.md)."""
    offenders = [
        str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if "dxb" in _imports(p)
    ]
    assert offenders == []


_SYNC_SQLALCHEMY_NAMES = {"create_engine", "sessionmaker", "Session", "scoped_session"}


def test_no_synchronous_session_use_anywhere():
    """All API data access is async (CLAUDE.md). A sync Session here would
    block the event loop for the whole duration of every query.

    Checked by resolving actual imported names rather than by substring:
    `async_sessionmaker` contains `sessionmaker`, and a docstring warning
    against sync usage would otherwise flag itself.
    """
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("sqlalchemy"):
                continue
            leaked = {a.name for a in node.names} & _SYNC_SQLALCHEMY_NAMES
            if leaked:
                offenders.append(f"{path.relative_to(SRC)} imports {sorted(leaked)}")
    assert offenders == []


def test_repositories_never_commit_or_add():
    """The read-only guarantee at the code layer."""
    offenders = []
    for path in (SRC / "repositories").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in (".commit()", ".add(", ".delete(", ".flush()"):
            if forbidden in text:
                offenders.append(f"{path.name}: {forbidden}")
    assert offenders == []


def test_shared_models_declare_no_relationships():
    """Load-bearing for async: an implicit lazy load inside an AsyncSession
    raises MissingGreenlet at runtime (CLAUDE.md, trap 1).

    Looks for actual `relationship(...)` calls, not the substring — the
    module's own docstring warns about relationships and would match.
    """
    import dxb_core.models as models

    tree = ast.parse(pathlib.Path(models.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "relationship"
    ]
    assert calls == []


# ---------------------------------------------------------------- config


def test_auth_defaults_to_enabled():
    assert build_settings().auth_disabled is False


def test_auth_can_be_disabled_for_local_development(monkeypatch):
    monkeypatch.setenv("DXB_AUTH_DISABLED", "1")
    assert build_settings().auth_disabled is True


def test_db_user_defaults_to_the_readonly_role():
    """Defaulting to the ELT's read-write user would quietly defeat layer 1."""
    assert build_settings().db_user == "dxb_readonly"


def test_dsn_uses_the_async_psycopg_driver():
    assert build_settings().dsn.startswith("postgresql+psycopg://")


def test_only_the_host_changes_to_point_at_a_read_replica(monkeypatch):
    monkeypatch.setenv("DXB_DB_HOST", "replica.internal")
    assert "@replica.internal:" in build_settings().dsn


def test_users_are_parsed_from_json(monkeypatch):
    monkeypatch.setenv(
        "DXB_API_USERS", json.dumps([{"username": "a", "password_hash": "h"}])
    )
    assert build_settings().users[0]["username"] == "a"


def test_malformed_user_json_fails_loudly_at_startup(monkeypatch):
    monkeypatch.setenv("DXB_API_USERS", "{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        build_settings()


def test_min_sample_default_is_conservative():
    """LLM safety: a median over a handful of sales is noise."""
    assert build_settings().default_min_sample >= 20


def test_page_limit_is_bounded():
    assert build_settings().max_page_limit <= 1000
