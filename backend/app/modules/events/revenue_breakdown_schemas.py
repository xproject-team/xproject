"""Pydantic schemas for GET /events/{id}/revenue-breakdown.

Structure mirrors the v5 popup mockup: top "Total Transato" (matching
Slesh's dashboard figure), then sales-by-bar, deposits, VAT/fiscal,
wristband cash flow, owner take-home, and diagnostics.

All money fields are Decimal EUR; the service converts from cents at
the response boundary so the API caller never deals with cents drift.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BarSale(BaseModel):
    bar_id: UUID
    bar_name: str
    bar_type: str  # drinks | food | merch | mixed
    revenue_eur: Decimal
    order_count: int


class SalesBreakdown(BaseModel):
    drinks_total_eur: Decimal
    drinks_by_bar: list[BarSale]
    food_total_eur: Decimal
    food_by_bar: list[BarSale]
    cash_desk_eur: Decimal
    subtotal_eur: Decimal  # drinks + food + cash_desk (gross, pre-VAT, pre-deposit-net)


class DepositsBreakdown(BaseModel):
    # Computed from stock_transactions filtered to deposit products
    # (matched by name pattern — category enum needs a 'deposit' value).
    # pos_line_status 'confirmed' = collected; 'refunded' = returned.
    collected_eur: Decimal
    collected_units: int
    returned_eur: Decimal
    returned_units: int
    forfeited_eur: Decimal       # collected - returned (net to owner)
    forfeited_units: int
    return_rate_pct: float | None


class FiscalBreakdown(BaseModel):
    vat_eur: Decimal
    fiscal_gross_eur: Decimal
    fiscal_net_eur: Decimal
    discounts_eur: Decimal


class CashFlowBreakdown(BaseModel):
    # Ricariche (wristband top-ups) are not exposed via the Slesh API
    # we currently have access to — stays None until manual entry lands.
    ricariche_eur: Decimal | None
    cash_desk_in_eur: Decimal
    spent_at_bars_eur: Decimal
    unspent_balance_eur: Decimal | None


class OwnerTakeHome(BaseModel):
    drinks_eur: Decimal
    deposits_forfeited_eur: Decimal
    food_gross_eur: Decimal
    food_share_pct: int
    food_share_eur: Decimal
    cash_desk_eur: Decimal
    total_eur: Decimal


class Diagnostics(BaseModel):
    order_count: int
    experience_order_count: int
    cash_desk_order_count: int
    cart_line_count: int


class RevenueBreakdown(BaseModel):
    event_id: UUID
    event_name: str

    # Top metric — matches Slesh "Transato"
    total_billed_eur: Decimal = Field(
        description=(
            "Gross order total — Slesh's __subtotal already includes VAT, so this "
            "is the customer-paid total across all orders. Slesh dashboard 'Transato' "
            "may additionally include wristband ricariche/unspent which the public API "
            "does not expose; manual entry required to display the full Slesh figure."
        )
    )
    transaction_count: int
    cancelled_eur: Decimal = Decimal("0.00")  # placeholder until cancellation tracking lands

    sales: SalesBreakdown
    deposits: DepositsBreakdown
    fiscal: FiscalBreakdown
    cash_flow: CashFlowBreakdown
    owner_take_home: OwnerTakeHome
    diagnostics: Diagnostics
