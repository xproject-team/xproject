"""Alembic async migration environment — supports autogenerate from ORM models."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base

# ─── Model imports (required for autogenerate to detect tables) ──────────
# Phase 4 models — currently active
from app.modules.auth.models import Tenant, User  # noqa: F401
from app.modules.venues.models import Venue  # noqa: F401
from app.modules.events.models import Event  # noqa: F401
from app.modules.products.models import Product  # noqa: F401
from app.modules.event_products.models import EventProduct  # noqa: F401
from app.modules.bar_stock.models import BarStock  # noqa: F401
from app.modules.recipes.models import Recipe, RecipeItem  # noqa: F401
from app.modules.stock_transactions.models import StockTransaction  # noqa: F401

# TODO: re-enable as each module's models are written in future phases.
# from app.modules.inventory.models import InventoryItem  # noqa: F401
# from app.modules.alerts.models import Alert  # noqa: F401
# from app.modules.predictions.models import Prediction  # noqa: F401
# from app.modules.anomaly.models import AnomalyEvent  # noqa: F401
# from app.modules.warehouse.models import ScanEvent  # noqa: F401
# from app.modules.reports.models import Report  # noqa: F401
from app.modules.chat.models import ChatAttachment, Channel, ChannelMember, ChatMention, ChatMessage  # noqa: F401
from app.modules.event_storage.models import SupplierProduct, EventStockItem  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = settings.database_url
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
