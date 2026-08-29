# Migration drill — apply and roll back, rehearsed on staging

Production applies migrations BY HAND (`railway ssh` → `alembic upgrade
head`; the Custom Start Command overrides the Dockerfile's automatic
upgrade). A bad migration therefore means a hand-run `alembic
downgrade` under pressure. This drill practises exactly that on
staging, using a throwaway migration built for the purpose:
`alembic/versions/ah1_staging_migration_drill.py` — one nullable TEXT
column on `venues` (single-digit rows), with a REAL `downgrade()`.

The drill was round-tripped on a scratch database before shipping
(ag1 → ah1, column present → downgrade → column gone, back at ag1), so
any deviation you see on staging is an environment problem, not a
defect in the drill file.

## The sequence (staging container: `railway ssh --service=xproject-staging`, from `/app`)

The verify block, used at every step — prints revision, drill-column
presence, and the venues row count in one shot:

```bash
python - <<'EOF'
import asyncio
from sqlalchemy import text
async def main():
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rev = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        col = (await db.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='venues' AND column_name='staging_drill_marker'"
        ))).scalar()
        n = (await db.execute(text("SELECT count(*) FROM venues"))).scalar()
        print(f"revision={rev}  drill_column_present={bool(col)}  venues_rows={n}")
asyncio.run(main())
EOF
```

| # | Command | Expected output — anything else is a stop |
|---|---------|-------------------------------------------|
| 1 | `alembic current` | `ag1` — note: NOT `ag1 (head)`, because the deployed code now carries ah1; "current ≠ head" is the normal pre-migration state |
| 2 | verify block | `revision=ag1  drill_column_present=False  venues_rows=N` — **write N down** |
| 3 | `alembic upgrade head` | exactly one line: `Running upgrade ag1 -> ah1, DRILL ARTIFACT …` |
| 4 | `alembic current` | `ah1 (head)` |
| 5 | verify block | `revision=ah1  drill_column_present=True  venues_rows=N` (same N) |
| 6 | `alembic downgrade ag1` | exactly one line: `Running downgrade ah1 -> ag1, …` (explicit target, not `-1` — name where you are going) |
| 7 | `alembic current` | `ag1` |
| 8 | verify block | `revision=ag1  drill_column_present=False  venues_rows=N` (same N) |

## What a PROBLEM looks like

- **Revision does not move** after step 3 (verify still says `ag1`):
  alembic is talking to a different database than the app —
  `DATABASE_URL` mismatch. Stop; nothing was migrated.
- **Silent no-op downgrade**: step 7 says `ag1` but step 8 says
  `drill_column_present=True`. The revision pointer moved without the
  schema change reverting — a broken `downgrade()`. This is the failure
  mode a `pass`-stub downgrade produces, and the reason the drill
  column check exists independently of `alembic current`.
- **Data loss**: `venues_rows` differs at any step. Nothing in this
  drill touches rows; any count change means something else is wrong —
  stop and investigate before proceeding.
- **More than one line of migration output** at step 3 or 6, or a
  "multiple heads" error: the migration chain has forked — stop.
- **`Can't locate revision`**: you are reasoning from filenames. Seven
  older version files have revision ids that differ from their
  filenames (`a2_add_bars_indexes.py` is revision `a2_add_bars_idx`,
  etc.). The drill file's id and filename match (`ah1`), but every
  command in this drill takes REVISION IDS — always from
  `alembic history`, never from `ls`. If you ever hit this error, that
  trap is what bit you.

## After the drill

Leave staging at `ag1` (i.e. finish with the downgrade — the rollback
IS the rehearsal). Then decide the artifact's fate before the next
promotion to `main`:

- **Remove it** (a one-commit revert of the drill file) if production
  should never see it — the tidy option; or
- **Keep it** and let production apply it at the next manual migration
  — the column is harmless (nullable, no default, no readers), and
  keeping it leaves a permanent rehearsal fixture.

Either is fine; what is not fine is promoting it without having decided.
