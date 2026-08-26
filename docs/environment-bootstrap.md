# Environment bootstrap

How a fresh XProject environment gets its schema and data. Written when
`app/scripts/seed.py` was removed (2026-08-26); see "Why seed.py is
gone" below.

## Fresh schema

Migrations alone build the schema from an empty database — proven on a
scratch database on 2026-08-24 (44 tables, head `ag1` at the time):

    alembic upgrade head

Note the deploy split: production and staging run a Custom Start Command
without the Dockerfile's `alembic upgrade head`, so **migrations are a
manual step** there (`railway ssh` → `alembic upgrade head`, then verify
with `alembic current`). When reasoning about the migration chain, trust
`alembic history` — 7 of the version files have a revision id that does
not match their filename.

## Data — staging and local dev

Fresh non-production environments are built with the generator:

    python -m app.scripts.build_staging_data        # in the container, from /app
    make seed                                       # local docker-compose stack

It is idempotent (wipes and rebuilds its own two tenants only) and
refuses to run unless the environment is provably non-production:
`ENVIRONMENT=staging` exactly, `POS_ADAPTER=fake`, and no
`SLESH_API_TOKEN`. It prints its account credentials on completion, and
its accounts can actually log in: it writes both `users.role` and the
authoritative `user_roles` table (the frontend login flow reads
`user_roles`; an account with only `users.role` set cannot sign in
through the UI).

## Data — production

Production identity is restored from backups, never seeded: any
recovery scenario that loses the tenant row also lost everything else,
and a database restore carries tenant, users, and roles together. See
docs/disaster-recovery.md.

## Why seed.py is gone

`app/scripts/seed.py` was removed rather than fixed:

- Broken since migration `a3` added `users.bar_id`: run standalone it
  crashed with `NoReferencedTableError` before creating its user
  (proven by execution on a scratch database, 2026-08-26).
- Even past that crash, it never inserted a `user_roles` row, so the
  owner it created could not log in through the frontend.
- It hardcoded a real person's name and email with a known starter
  password — not something that should be runnable anywhere, and its
  only distinct purpose after `build_staging_data` existed.

Standalone-script rule that came out of the same incident: any script
that writes through the ORM imports `app.models_registry` first, so the
FK graph is complete regardless of which models the script names.
