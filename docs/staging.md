# Staging — operating manual

Written for an operator who was not part of the build week. Companion
docs: [environment-bootstrap.md](environment-bootstrap.md) (fresh
environments), [migration-drill.md](migration-drill.md) (the rollback
rehearsal), [job-status-semantics.md](job-status-semantics.md) (the
silent-ok findings that must outlive the week that found them).

## What staging is for — and is not

Staging exists to **rehearse production procedures where mistakes cost
nothing**: migrations and their rollbacks, event lifecycle transitions,
the post-event pipeline, POS ingestion edge cases (refunds, unmapped
shops, parking), and deploys themselves. Every change reaches staging
before production because staging tracks `develop` and production
tracks `main`.

It is **not**:
- **a demo environment** — the data is generated, the tenants are
  synthetic, and anything on it may be wiped without notice;
- **a backup** — nothing on staging can restore production; recovery is
  docs/disaster-recovery.md;
- **connected to the POS provider** — by client ruling, no real guest
  data reaches staging by any route. The integration runs against a
  fake adapter serving generated, provider-shaped payloads.

## The five services (Railway project `lucid-consideration`, environment `staging`)

| Service | What it does |
|---|---|
| `xproject-staging` | FastAPI backend. Same image as production, started with the same Custom Start Command (no automatic migrations). |
| `xproject-worker-staging` | arq worker: per-minute POS polling, 5-minute alert/report/intelligence crons, post-event jobs. |
| frontend | Vite/React, built at container start; `VITE_API_BASE_URL` points at the staging API. |
| Postgres | Staging's own database and volume. 44 tables, migrated by hand. |
| Redis | Staging's own queue/cache/pub-sub. |

Access: `railway ssh --service=<name> --environment=staging`; work from
`/app`. The container has no `psql` — queries run through Python
(`app.core.database.AsyncSessionLocal`), see the paste-ready blocks in
the linked docs.

Key service variables: `ENVIRONMENT=staging`, `POS_ADAPTER=fake`,
staging-unique `SECRET_KEY`, staging `DATABASE_URL`/`REDIS_URL`,
`LOG_LEVEL=DEBUG`. Deliberately ABSENT (not empty — absent):
`SLESH_API_TOKEN`, `SLESH_BRAND_ID`, `SLESH_BASE_URL`,
`ANTHROPIC_API_KEY`, all `S3_*`.

## Branch model and the day-to-day loop

Staging tracks **`develop`** (auto-deploys on push). Production tracks
**`main`**, which is protected: PRs only, merge commits forbidden.
Promotion is therefore a squash-merge PR — one commit per promotion on
`main`, with the PR as the audit trail.

```bash
# day to day: work lands on develop, which deploys to staging
git push origin develop            # → staging redeploys

# promote to production, once verified on staging
gh pr create --base main --head develop \
  --title "promote: <summary> (develop @ $(git rev-parse --short develop))"
# merge in the UI with "Squash and merge" → production redeploys from main

# after any promotion involving migrations: apply them BY HAND on
# production (nothing runs them automatically) — see Migrations below
```

Rules: `main` receives only promotion PRs from `develop`, never direct
work. A hotfix goes develop → staging verify → promote immediately.

## Rebuilding the data from scratch

```bash
railway ssh --service=xproject-staging --environment=staging
# from /app:
python -m app.scripts.build_staging_data
```

- **Guards** — the script refuses unless all three hold:
  `ENVIRONMENT` is exactly `staging`, `POS_ADAPTER=fake`, and
  `SLESH_API_TOKEN` is unset. There is no override flag.
- **What it wipes**: its own two tenants only (`staging-alpha`,
  `staging-beta`) and everything they own, including their
  `event_orders` (deleted explicitly — see Known limitations). The
  hand-seeded `staging-demo` tenant is never touched.
- **What it builds**: two tenants; owner+manager accounts that can
  actually log in (both `users.role` and the authoritative `user_roles`
  are written); the full catalog mapped to the fake adapter's ids;
  three completed events with ~5,000 ingested orders; one live event
  (fed continuously by the fake); draft/active events; reports in both
  languages including the diverged-version and failed-row rehearsal
  shapes; fitted forecast models for alpha and deliberately none for
  beta.
- **Account passwords print at the end of the run.** (Currently fixed
  strings committed to the repo — a recorded decision under review; see
  the credentials discussion in the engagement log.)
- **Orphan cleanup requires the `--purge-orphans` flag — it does not
  run by default, by design, permanently.** The default invocation
  touches only the generator's own two tenants; the purge is the one
  operation that deletes rows outside them (orphans whose event or
  tenant no longer exists, across every event/tenant-scoped table), so
  it stays an explicit choice. A run without the flag prints
  `purge: NOT requested (--purge-orphans absent)` so a no-purge
  transcript can never be mistaken for a purge; a run with it prints a
  per-table removal list and a post-commit verification line naming the
  database it counted against (`verified from a new connection: N
  orphaned rows remain (database=…)`), and refuses to build if N > 0.

The live event is fed at any hour: full order curve 16:00–02:00 local
(peak 18:00), a small deterministic trickle otherwise.

**The awkward shapes are features — do not tidy them away.** The
generated data deliberately includes uncomfortable asymmetries: diverged
IT/EN report versions, a failed regeneration row, a deliberately
unmapped bar, a ghost shop. These have earned their keep twice over:
the diverged IT/EN versions were added to catch the 22 Aug
sibling-collision defect, and on 2 Sep the same asymmetry exposed a
second, unrelated defect (the season view drawing its bars from a
different report population than its totals — invisible on uniform data,
where the IT/EN pair agrees by coincidence). Symmetric, convenient
rehearsal data hides exactly the bug classes staging exists to catch;
anyone "cleaning up" these shapes is deleting tripwires.

## Verifying isolation — proof, not assurance

Isolation from the POS provider is **observable in logs**, and was
additionally proven at the OS socket layer in the test suite
(`tests/test_fake_pos_adapter_safety.py`: every adapter call under a
patched socket layer that raises on any connection attempt, with a
control case proving the real adapter trips it).

Operational checks, in the container:

```bash
# 1. Configuration: both must print '' (empty)
python -c "from app.core.config import settings; print(repr(settings.slesh_api_token), repr(settings.slesh_brand_id))"

# 2. Adapter selection: must print 'fake'
python -c "from app.core.config import settings; print(settings.pos_adapter)"
```

Log-line proof (worker logs):
- **Correctly isolated and ACTIVE** (POS_ADAPTER=fake): the per-minute
  poll logs `poll_slesh_for_event {'status': 'ok', 'orders_seen': N,…}`
  with the fake serving orders — and NO `SleshAdapter`/HTTP lines ever
  appear, because the factory constructs `FakePOSAdapter` with no
  credentials, URL, or HTTP client at all.
- **Isolated but INERT** (adapter unconfigured — the pre-fake state):
  `cron_poll_slesh_for_all_live_events {'status':'skipped','reason':'no_token','enqueued':0}`
  every minute, plus (at DEBUG) `cron_poll_slesh: skipped (no POS
  adapter configured — SLESH_API_TOKEN absent and POS_ADAPTER is not
  'fake')`. This state is safe but rehearses nothing.

## Migrations — manual, always

Neither production nor staging runs migrations at deploy (the Custom
Start Command omits `alembic upgrade head`). After any deploy that
carries migrations:

```bash
railway ssh --service=xproject-staging --environment=staging
alembic upgrade head
alembic current        # must print the expected head
```

Trust `alembic history` for revision ids — seven version files have ids
that differ from their filenames. The apply-and-roll-back procedure is
rehearsed via [migration-drill.md](migration-drill.md); run the drill
once per operator, and again before any migration you are nervous
about.

## Known limitations, honestly

- **The fake adapter is not the provider.** It reproduces the verified
  wire contract (fiscal identity `subtotal = fiscal_gross + deposit`,
  VAT on the deposit-inclusive subtotal, both order types, deposit
  returns as refunded lines, bare-string user/operator ids, unmapped
  shops) but not the provider's transport: no pagination, rate limits,
  retries, timeouts, or malformed payloads. Transport-layer behavior is
  untested here by design.
- **`raw_extras` carries `user`/`operator` but not `cart`** — matching
  production's ingester, which deliberately stores only the identity
  blobs to keep row size manageable.
- **`event_orders` has no foreign keys in the real schema** (migration
  `eo1` created plain UUID columns; the ORM model claims CASCADE FKs it
  does not have). The generator compensates — its wipe deletes its
  tenants' orders explicitly, and `--purge-orphans` clears older
  backlog — but the schema drift itself remains until a gated
  production migration adds the FKs (production needs an orphan audit
  first). Until then, anything else that deletes events or tenants
  outside the generator will orphan orders silently.
- **Chat attachments are disabled** (2026-09-01), visibly: the picker
  shows "Attachments are unavailable." No environment has object
  storage; the backend
  endpoints remain intact. Revival checklist:
  docs/post-sundance-backlog.md.
- **Historical events' reports show Guests as unavailable** — the
  generator does not build customer features for pre-completed events;
  only a real `end_event()` close does. This is a faithful
  graceful-degradation shape.

## Troubleshooting — what actually happened this week

**Live event receives zero orders, poll reports ok every minute.**
Check in this order:
1. Is `POS_ADAPTER=fake` set on the WORKER service (not only the API)?
   If unset, the cron logs `status: skipped, reason: no_token`.
2. Is there a LIVE event? `cron_poll` logs `live_events: 0` if not.
3. Are you on a build older than the off-peak-trickle fix? The original
   fake generated orders only 16:00–02:00 local; a fresh live event
   polled at midday starved for hours while every layer reported ok.
   (This was the actual Day-5 cause — a stale poll cursor was suspected
   and ruled out: poll-state rows die with their tenant on regenerate.)
4. Only then suspect poll state: inspect `slesh_poll_state` for the
   tenant — a cursor far in the future would silence polling, but no
   such case has been observed.

**Login fails with "not authorized for this role" though the user row
exists.** The role lives in two places and the frontend login flow
reads `user_roles`, not `users.role`. A hand-inserted user without a
`user_roles` row cannot log in. Use the generator's accounts, or insert
the `user_roles` row. (The old `seed.py` had exactly this bug and was
removed.)

**A script passes the test suite but crashes standalone with
`NoReferencedTableError`.** Pytest imports the full model registry;
`python -m` imports only the script's closure, so SQLAlchemy cannot
resolve FKs to unimported models. Any standalone script that writes
through the ORM must `import app.models_registry` first. The test that
guards this class runs the real entry point in a subprocess.

**A job reports 'ok' but accomplished nothing.** That is a known,
systemic pattern — see
[job-status-semantics.md](job-status-semantics.md) before trusting any
worker status line.
