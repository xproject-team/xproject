"""Abstract base class defining the POS adapter interface.

This contract is read-only by construction. POS data flows FROM the vendor
TO XProject; we never push transactions into the vendor's system. Subclasses
can therefore only define methods that read state — there is no write surface.

WHY THE CONTRACT LOOKS LIKE THIS:
The original BasePOSAdapter (March 28) defined `process_transaction` and
`get_balance`, both of which assumed the POS was an OLTP-style payment
processor that XProject would push to. Investigation in late April 2026
established that Slesh — the chosen POS for Sundance — exposes neither
endpoint. Slesh's POS terminals create orders independently; XProject is
an observer that polls. We rewrote this contract to match that reality.

If a future POS vendor (e.g. iPratico, Phase 2) is added, its adapter
subclasses BasePOSAdapter and implements the same five read methods.
The downstream pipeline — ingestion, alerts, predictions, reports — does
not need to know which adapter is in use.

Spec reference: docs/slesh-integration-roadmap.md §B2 + Sync Plan Delta 2.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Forward-declared schema imports avoid any chance of an adapter module
    # being imported during schemas.py initialisation. At runtime these
    # types are just string annotations — no circular import is possible.
    from app.modules.pos.schemas import (
        Brand,
        Category,
        Order,
        Product,
        Shop,
    )


class BasePOSAdapter(ABC):
    """Read-only contract every POS adapter must fulfil.

    All five methods are async because every implementation will perform
    network I/O. Concrete adapters (e.g. SleshAdapter in B3) layer rate
    limiting, retry, and circuit-breaker logic over the raw HTTP calls.
    """

    # ─── Health check ───────────────────────────────────────────────────
    @abstractmethod
    async def verify_token(self) -> "Brand":
        """Confirm credentials work and return the brand record.

        Used at application startup and as a health-check probe. A failure
        here means our integration is misconfigured (wrong token, expired
        token, network down) — every other method will fail until this passes.
        """
        ...

    # ─── Reference data sync (one-shot, per event) ──────────────────────
    @abstractmethod
    async def list_shops(
        self,
        experience_id: str | None = None,
    ) -> list["Shop"]:
        """List shops for the brand. Optionally filter by experience.

        A 'shop' in vendor terminology maps to one of our `bars`. Each shop
        has a stable `_id` which we store in `bars.slesh_negozio_id`.
        """
        ...

    @abstractmethod
    async def list_categories(
        self,
        experience_id: str | None = None,
    ) -> list["Category"]:
        """List product categories for the brand.

        Categories anchor our tier-mapping (Basic / Standard / Premium /
        Ultra-premium). Stored locally with a Slesh `external_pos_id` link.
        """
        ...

    @abstractmethod
    async def list_products(
        self,
        experience_id: str | None = None,
    ) -> list["Product"]:
        """List physical and digital products for the brand.

        Products feed our drink catalog and recipe joins. The vendor returns
        names as a localised dict ({it: 'Mojito', en: 'Mojito'}); the adapter
        is responsible for picking the primary locale at the boundary.
        """
        ...

    # ─── Live consumption stream (the heart of the integration) ─────────
    @abstractmethod
    def list_orders(
        self,
        since_ts:      datetime,
        until_ts:      datetime,
        *,
        experience_id: str | None = None,
        shop_id:       str | None = None,
        order_type:    str | None = "experience",
    ) -> AsyncIterator["Order"]:
        """Stream orders in [since_ts, until_ts] as parsed Order models.

        Returns an async generator so callers can iterate over thousands of
        orders without loading them all into memory. Pagination is handled
        internally — the caller never sees cursor mechanics.

        Default `order_type='experience'` matches Sundance's NFC-cashless
        flow. Set to None to receive all order types (cash-desk + express
        + experience), e.g. for post-event reconciliation reports.
        """
        ...
