"""Complete SQLAlchemy model registry — import this before standalone ORM work.

WHY THIS EXISTS: SQLAlchemy resolves foreign keys against whatever
tables happen to be registered in metadata at flush time. Inside the API
or the test suite that is always everything (app.main / pytest
collection import the world). A script run standalone via `python -m`
registers only what IT imports — and the first real staging run of
build_staging_data crashed with

    NoReferencedTableError: users.bar_id could not find table 'bars'

because the script imported User but nothing had imported Bar. Tests
were green; the entry point was broken. Any app/scripts/ module that
adds/flushes ORM objects has the same latent failure mode unless its
import closure happens to cover every FK target.

The rule: a standalone script that writes through the ORM imports this
module first. One line, closes the whole class:

    import app.models_registry  # noqa: F401 — complete the FK graph

Keep this list in sync with app/modules/*/model*.py. It imports model
modules only — no routers, no services, no side effects beyond mapper
registration.
"""
from __future__ import annotations

# fmt: off
from app.modules.alerts import models as _alerts_models                      # noqa: F401
from app.modules.anomaly import models as _anomaly_models                    # noqa: F401
from app.modules.auth import models as _auth_models                          # noqa: F401
from app.modules.bar_stock import models as _bar_stock_models                # noqa: F401
from app.modules.bars import device_model as _bars_device_model              # noqa: F401
from app.modules.bars import models as _bars_models                          # noqa: F401
from app.modules.chat import models as _chat_models                          # noqa: F401
from app.modules.customer_analytics import models as _customer_analytics_models  # noqa: F401
from app.modules.event_products import models as _event_products_models      # noqa: F401
from app.modules.event_storage import models as _event_storage_models        # noqa: F401
from app.modules.events import models as _events_models                      # noqa: F401
from app.modules.inventory import models as _inventory_models                # noqa: F401
from app.modules.pos import models as _pos_models                            # noqa: F401
from app.modules.pos import poll_state_models as _pos_poll_state_models      # noqa: F401
from app.modules.predictions import models as _predictions_models            # noqa: F401
from app.modules.products import models as _products_models                  # noqa: F401
from app.modules.recharge import models as _recharge_models                  # noqa: F401
from app.modules.recipes import models as _recipes_models                    # noqa: F401
from app.modules.recipes import template_models as _recipes_template_models  # noqa: F401
from app.modules.reports import models as _reports_models                    # noqa: F401
from app.modules.stock_transactions import models as _stock_transactions_models  # noqa: F401
from app.modules.venues import models as _venues_models                      # noqa: F401
from app.modules.warehouse import models as _warehouse_models                # noqa: F401
# fmt: on
