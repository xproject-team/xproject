"""Every app/scripts module must be importable standalone with a
resolvable FK graph — the class of failure that broke seed.py, the
staging generator, and (latently) a dozen ops scripts.

Mechanism: pytest's collection imports the full model registry, so any
in-process test sees a world where every table is known — while
`python -m app.scripts.X` in the container imports only the script's
own closure, and SQLAlchemy cannot resolve FKs to unimported models
(NoReferencedTableError at first flush). Three incidents this
engagement came from exactly this gap between test context and runtime
context.

This test runs the audit probe as CI: for EVERY script (globbed, so
future scripts are covered automatically), a fresh interpreter imports
the module and forces full FK-graph resolution — the same resolution a
flush performs. The fix for a failure is one line:

    import app.models_registry  # noqa: F401 — complete the FK graph

Stated limitation: a script that imports models only lazily inside
functions passes vacuously here; for those, entry-point subprocess
tests (see test_staging_data_generator) are the deeper check. This
test covers the class that has actually bitten.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

_SCRIPTS = sorted(
    p.stem
    for p in (pathlib.Path(__file__).parent.parent / "app" / "scripts").glob("*.py")
    if p.stem != "__init__"
)


@pytest.mark.parametrize("script", _SCRIPTS)
def test_script_imports_standalone_with_resolvable_fk_graph(script: str):
    probe = (
        f"import importlib; importlib.import_module('app.scripts.{script}'); "
        "from app.core.database import Base; "
        "list(Base.metadata.sorted_tables)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"app/scripts/{script}.py cannot run standalone — its import "
        "closure leaves the FK graph unresolvable (the seed.py failure "
        "class). Add: import app.models_registry\n"
        f"stderr tail:\n{result.stderr[-800:]}"
    )
