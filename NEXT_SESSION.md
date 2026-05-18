# Next Session — Pick up here

**Last session:** 2026-05-18 — State-of-project audit completed.
**Audit doc:** docs/audits/state-of-project-2026-05-17.md (1573 lines)
**Action plan:** docs/pre-sundance-must-ship.md
**Backlog:** docs/post-sundance-backlog.md

## Tomorrow's work — WS1 RF33 Phase 1D auth migration

**Estimate:** 1-2 days
**Why first:** auth dual-state (users.role + user_roles) is currently
stable but will drift on any role-write.  Phase 9 builds on this.

## Scope

1. Read RF33 in audit doc Appendix D (full evidence chain)
2. Add get_active_role(current_user, request) helper if missing
3. Migrate 20 call sites from current_user.role to helper
4. Alembic migration p2_drop_users_role_column
5. Browser-test all 4 roles (Owner, Manager, Bartender, Warehouse)

## Recon already done

Audit listed all 20 call sites with file:line precision.  See
audit doc Appendix D Layer 3 query C output.

## Standard discipline

- Smallest commits — one file at a time
- Browser test per file before committing
- Backup users + user_roles tables before migration step 4
- pg_dump xproject_dev > backups/xproject_dev_pre_rf33.sql

## Audit findings reference

CRITICAL: RF21 (Phase 8 dress rehearsal), RF33 (this)
HIGH:     RF37 (real Phase 7), RF41 (change-password)
See must-ship.md for full sequence May 19 to June 19.
