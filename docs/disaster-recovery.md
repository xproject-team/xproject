# XProject — Disaster Recovery Runbook

**Last verified:** 2026-05-23 — backup + restore drill on `xproject_dev`
(522 stock_transactions, 19 alerts, 10 users) — full round-trip in <1 second.

This document is for the worst-case scenario at Sundance: the database is
corrupted, the server crashed, a bad migration nuked rows, etc. The goal
is to be back online in under 10 minutes.

---

## 1. Pre-event backup ritual

Run this immediately before Sundance go-live, and again every 30 minutes
during the event:

```bash
cd ~/Projects/xproject
./scripts/backup-db.sh pre-go-live      # T-0: final pre-event snapshot
./scripts/backup-db.sh hour-1           # T+60min during event
./scripts/backup-db.sh hour-2           # T+2h
# etc.
```

Each snapshot is timestamped and lives in `./backups/`. The live dev DB
is ~350 KB, so 30-minute snapshots over a 6-hour event = ~4 MB total.
Disk cost is trivial; insurance value is enormous.

---

## 2. Daily backup (set-and-forget)

If you want hands-off backups, add this to crontab on the host:

```cron
# Every hour, full DB snapshot
0 * * * * cd /Users/mohammadhesam/Projects/xproject && ./scripts/backup-db.sh hourly >> /tmp/xproject-backup.log 2>&1
```

The script handles directory creation and timestamping automatically.

---

## 3. Recovery — three failure modes

### 3.1 "The DB is corrupt but the server is up"

1. Stop the API to prevent further writes:
```bash
   pkill -f "uvicorn app.main"
```
2. Find the most recent backup:
```bash
   ls -lat ~/Projects/xproject/backups/ | head -5
```
3. Restore over the live DB (requires typing `YES` to confirm):
```bash
   cd ~/Projects/xproject
   ./scripts/restore-db.sh backups/<filename>.sql xproject_dev
```
4. Restart the API:
```bash
   cd backend && source venv/bin/activate
   uvicorn app.main:app --host 0.0.0.0 --port 8000 &
```
5. Verify with the deep health check:
```bash
   curl -s http://localhost:8000/api/v1/health/deep | python3 -m json.tool
```

Expected total recovery time: **<2 minutes**.

### 3.2 "The Postgres container won't start"

1. Check `docker ps` — is the postgres container even running?
2. If not: `docker compose restart postgres` (or relevant container name)
3. If it crash-loops:
```bash
   docker compose logs postgres | tail -50
```
   Most common cause is disk full or corrupt WAL files.
4. Worst case: delete the data volume and restore from backup:
```bash
   docker compose down
   docker volume rm xproject_postgres_data    # ⚠️ destroys data
   docker compose up -d postgres
   sleep 5
   ./scripts/restore-db.sh backups/<filename>.sql xproject_dev
```

Expected total recovery time: **<5 minutes**.

### 3.3 "The whole machine is gone"

Worst-case disaster — laptop stolen, server died. You need:

1. A second machine with Python 3.13, Postgres 14+, Redis, MinIO.
2. The latest `.sql` backup (sync `backups/` to cloud storage daily!)
3. The repo clone: `git clone github.com/xproject-team/xproject`
4. Reconstitute with the runbook in `docs/setup-from-scratch.md`
   (TODO: this doc doesn't exist yet — write before Sundance).

Expected total recovery time: **30-60 minutes** (mostly machine setup).

---

## 4. Backup rotation policy

The `backups/` directory will grow over time. Manual rotation:

```bash
# Keep only the last 50 snapshots
cd ~/Projects/xproject/backups/
ls -t *.sql | tail -n +51 | xargs rm -f
```

Pre-Sundance recommendation: **do not auto-delete anything**. Manual
cleanup post-event.

---

## 5. Off-site backup (PRE-SUNDANCE TODO)

Local backups protect against software corruption but NOT physical loss
of the machine. Before Sundance, sync `backups/` to one of:

- **iCloud Drive** — easiest, but not encrypted in transit by default
- **rsync to a second machine** — requires you to own a second machine
- **S3 bucket** — best, but costs money and requires AWS setup
- **GitHub release attachment** — free, encrypted, slow upload

Minimal viable option: `rsync` the backups dir to your iCloud Drive folder
in a cron job daily. Pre-Sundance, manually copy snapshots to your phone.

---

## 6. Verification — the only thing that matters

**A backup you've never restored is not a backup.** Test the restore
flow at least once per week leading up to Sundance:

```bash
./scripts/backup-db.sh weekly-drill
./scripts/restore-db.sh backups/<latest>.sql      # restores to scratch DB
# Verify row counts match live
psql -d postgres -c "DROP DATABASE xproject_restore_test;"
```

If the row counts diverge, **stop and investigate before continuing
development**. A silent corruption in the backup pipeline is the worst
possible disaster scenario.
