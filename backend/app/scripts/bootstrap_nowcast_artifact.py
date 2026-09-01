#!/usr/bin/env python3
"""bootstrap_nowcast_artifact.py — one-time seed of Noma Group's nowcast
model_artifacts row from the original 9-event external Sundance dataset
(app/modules/predictions/nowcast/data/*.parquet).

Part of the 2026-08 fix moving the nowcast off a single shared,
process-wide parquet file (a cross-tenant data leak: every tenant's
Dashboard forecast was computed from the SAME historical basis,
regardless of which tenant was asking) onto model_artifacts
(tenant_id-scoped, versioned, durable — see nowcast/predictor.py's
module docstring for the full rationale).

That 9-event dataset is Noma Group's own real historical data (built
from their own past "Sundance" events by scripts/
extract_historical_sundance.py — Sundance is Noma Group's event brand,
confirmed against this DB: they are the only non-test/non-simulation
tenant). It belongs to them, and ONLY to them — this script seeds it
into Noma Group's tenant_id specifically (via
nowcast/retrain.py::bootstrap_from_static_dataset, the reusable,
directly-tested core of this). Every other tenant deliberately starts
with no nowcast artifact at all and accumulates one purely from their
own completed events going forward (see nowcast/retrain.py's normal
retrain_from_completed_events).

Idempotent — safe to re-run; refuses to overwrite an existing active
artifact for this tenant (from a prior run of this script, or from a
real retrain having already happened since).

Usage (once per environment — local dev, and once manually against
production after this fix deploys, since Railway does not run
one-off scripts automatically):
    venv/bin/python scripts/bootstrap_nowcast_artifact.py
"""
from __future__ import annotations

import app.models_registry  # noqa: F401 — complete the FK graph for standalone runs

import asyncio
import sys
from pathlib import Path
from uuid import UUID


from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant  # noqa: F401 — prime mapper
from app.modules.predictions.models import ModelArtifact  # noqa: F401 — prime mapper
from app.modules.predictions.nowcast.retrain import bootstrap_from_static_dataset

NOMA_TENANT_ID = UUID("25ef916c-a288-44ae-b17c-8dfd09390834")


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await bootstrap_from_static_dataset(session, NOMA_TENANT_ID)

    if result["status"] == "already_bootstrapped":
        print(
            f"Noma Group already has an active nowcast artifact "
            f"(id={result['existing_artifact_id']}, version={result['existing_version']}) "
            f"— nothing to do."
        )
    else:
        print(
            f"✓ Bootstrapped nowcast artifact for Noma Group: version=1, "
            f"n_events={result['n_training_events']}, n_transactions={result['n_training_rows']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
