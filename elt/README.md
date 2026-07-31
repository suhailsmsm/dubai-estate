# dxb ELT service

Collects Dubai Land Department open data (transactions, rents, projects) into a local
Postgres star schema. See ../docs/PLAN.md for the full design.

Run everything from the repo root:

```
docker compose up -d --build         # db + scheduled daily pipeline
docker compose run --rm elt dxb init                      # migrations + seed
docker compose run --rm elt dxb backfill --from 2026-01-01  # historical load
docker compose run --rm elt dxb stats
```

## Dev setup

One-time, per clone — wires up the tracked pre-commit hook
(`.pre-commit-config.yaml`, blocks commits on `ruff check` failures in
`elt/`; runs via `elt/`'s own uv-managed venv, no separate ruff install):

```
uv run --project elt pre-commit install
```
