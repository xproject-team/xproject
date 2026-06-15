"""Pydantic schemas for GET /events/{id}/revenue-breakdown.

Every monetary field has a description that ends up as a tooltip in the
popup, so the meaning of each number is unambiguous.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BarSale(BaseModel):
    bar_id: UUID
    bar_name: str
    bar_type: str = Field(description="One of: drinks | food | mixed | merch | service")
    revenue_eur: Decimal = Field(description="Sum of order subtotals at this bar (incl. VAT + deposits)")
    order_count: int


class SalesBreakdown(BaseModel):
    drinks_total_eur: Decimal = Field(description="Drinks-bars revenue (bar_type in drinks | mixed)")
    drinks_by_bar: list[BarSale]
    food_total_eur: Decimal = Field(description="Food-truck revenue. Vendor share is paid out separately.")
    food_by_bar: list[BarSale]
    cash_desk_eur: Decimal = Field(description="Direct cash purchases at cash-desk (no wristband)")
    subtotal_eur: Decimal = Field(description="drinks + food + cash_desk (sanity check)")


class DepositsBreakdown(BaseModel):
    collected_eur: Decimal = Field(description="Cup/bottle deposits paid by customers at sale. Already included in customer spending above.")
    collected_units: int
    returned_eur: Decimal = Field(description="Deposits refunded when customer returned their cup/bottle.")
    returned_units: int
    forfeited_eur: Decimal = Field(description="Deposits kept by owner for cups/bottles never returned (owner income).")
    forfeited_units: int
    return_rate_pct: float | None = Field(description="Percent of deposits returned (lower = more forfeited income).")


class FiscalBreakdown(BaseModel):
    vat_eur: Decimal = Field(description="VAT collected, must be remitted to Italian Stato. ~10% rate. Not owner income.")
    fiscal_gross_eur: Decimal = Field(description="Revenue reported to fiscal authorities (= total gross minus deposits).")
    fiscal_net_eur: Decimal = Field(description="Fiscal revenue net of VAT.")
    discounts_eur: Decimal = Field(description="Promo discounts applied across orders.")


class CashFlowBreakdown(BaseModel):
    ricariche_eur: Decimal | None = Field(default=None, description="Wristband top-ups total. Not exposed by Slesh public API - requires manual entry from dashboard.")
    cash_desk_in_eur: Decimal = Field(description="Direct cash flow at cash-desk.")
    spent_at_bars_eur: Decimal = Field(description="Money spent at drinks + food bars (excludes cash-desk).")
    unspent_balance_eur: Decimal | None = Field(default=None, description="Computed as ricariche - spent (only available once ricariche is manually entered).")


class OwnerWaterfall(BaseModel):
    """Step-by-step computation of owner's net cash from gross customer spending."""
    gross_revenue_eur: Decimal = Field(description="Starting amount: total customer spending (= total_billed_eur).")
    minus_deposits_returned_eur: Decimal = Field(description="Subtract: deposit refunds returned to customers at cup/bottle return.")
    minus_vat_eur: Decimal = Field(description="Subtract: VAT to remit to Italian Stato. Legal obligation, not owner income.")
    minus_food_vendor_share_eur: Decimal = Field(description="Subtract: food truck vendor's revenue share.")
    net_takehome_eur: Decimal = Field(description="Owner's net cash. Before staff, venue, supplier costs.")
    food_owner_share_pct: int = Field(description="Percent of food revenue kept by owner (e.g. 30 means owner 30% / vendor 70%).")
    food_owner_share_eur: Decimal = Field(description="Food revenue portion kept by owner.")
    food_vendor_share_pct: int = Field(description="Percent of food revenue paid to vendor (= 100 - owner_share_pct).")


class Diagnostics(BaseModel):
    order_count: int = Field(description="Total non-refunded orders.")
    experience_order_count: int = Field(description="Orders via wristband POS (drinks/food bars).")
    cash_desk_order_count: int = Field(description="Direct cash orders at cash-desk.")
    cart_line_count: int = Field(description="Total cart lines across all non-refunded orders.")
    refunded_order_count: int = Field(default=0, description="Number of orders fully refunded (excluded from revenue).")


class RevenueBreakdown(BaseModel):
    event_id: UUID
    event_name: str
    total_billed_eur: Decimal = Field(
        description=(
            "Total customer spending at the venue. Sum of order subtotals across "
            "all non-refunded orders (already includes VAT and deposits). The headline "
            "revenue figure. Note: Slesh dashboard 'Transato' additionally includes "
            "unspent wristband top-ups (not exposed via Slesh public API), so it may "
            "be higher than this figure by the unspent amount."
        )
    )
    transaction_count: int = Field(description="Number of non-refunded orders.")
    cancelled_eur: Decimal = Decimal("0.00")
    sales: SalesBreakdown
    deposits: DepositsBreakdown
    fiscal: FiscalBreakdown
    cash_flow: CashFlowBreakdown
    owner_waterfall: OwnerWaterfall
    diagnostics: Diagnostics
