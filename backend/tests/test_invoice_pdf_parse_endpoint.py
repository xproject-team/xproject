"""Integration tests for POST /api/v1/warehouse/invoices/parse-pdf.

These tests exercise the full HTTP path:
  multipart/form-data PDF upload
    -> FastAPI dependency injection (auth, file)
    -> parse_invoice_pdf()
    -> JSON serialization of ParsedInvoice
    -> response shape

They complement the unit tests in test_invoice_pdf_parser.py, which cover
the parser in isolation. If a unit test fails, the parser is broken. If
an integration test fails, the *endpoint* is broken (auth, file handling,
JSON serialization).
"""
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient


FATTURE_DIR = Path(__file__).parent / "fixtures" / "fatture"
PARTESA_PDF = FATTURE_DIR / "partesa_sample.pdf"


# ─── Happy path ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_pdf_returns_full_structure(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """Upload the PARTESA fixture, expect a 200 with header + 31 items."""
    pdf_bytes = PARTESA_PDF.read_bytes()
    resp = await client.post(
        "/api/v1/warehouse/invoices/parse-pdf",
        headers=owner_headers,
        files={"file": ("partesa.pdf", pdf_bytes, "application/pdf")},
    )

    assert resp.status_code == 200, f"unexpected: {resp.status_code} {resp.text[:300]}"
    data = resp.json()

    # Top-level shape
    assert set(data.keys()) >= {"header", "items", "raw_text"}

    # Header — same expectations as the unit tests, but via JSON now
    h = data["header"]
    assert h["supplier_name"] == "PARTESA S.R.L."
    assert h["supplier_vat"] == "IT09806270154"
    assert h["customer_name"] == "SUNDANCE SRLS"
    assert h["customer_vat"] == "IT17156041000"
    assert h["invoice_number"] == "5812120214"
    assert h["invoice_date"] == "2026-06-09"     # date serializes to ISO string
    assert Decimal(h["total_imponibile"]) == Decimal("15107.39")
    assert Decimal(h["total_iva"]) == Decimal("3323.63")
    assert Decimal(h["total_document"]) == Decimal("18431.02")

    # Items — full 31, JSON-serialized
    items = data["items"]
    assert len(items) == 31
    # Spot check the first item
    assert items[0]["line_num"] == 10
    assert items[0]["description"] == "WYBOROWA 1LT VODKA"
    assert items[0]["unit"] == "BO"
    assert Decimal(items[0]["qty"]) == Decimal("30.00")
    assert Decimal(items[0]["line_total_eur"]) == Decimal("390.04")
    # SPESE VARIE never makes it into items
    assert all(it["line_num"] != 320 for it in items)


# ─── Auth ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_pdf_requires_authentication(client: AsyncClient) -> None:
    """No Authorization header -> 401 (FastAPI dependency rejects)."""
    pdf_bytes = PARTESA_PDF.read_bytes()
    resp = await client.post(
        "/api/v1/warehouse/invoices/parse-pdf",
        files={"file": ("partesa.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 401


# ─── Bad inputs ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_pdf_rejects_non_pdf_content_type(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """Wrong content-type -> 415 Unsupported Media Type."""
    resp = await client.post(
        "/api/v1/warehouse/invoices/parse-pdf",
        headers=owner_headers,
        files={"file": ("not_a_pdf.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 415
    body = resp.json()["detail"]
    assert body["error"] == "unsupported_media_type"


@pytest.mark.asyncio
async def test_parse_pdf_rejects_empty_file(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """Zero-byte upload -> 422 (caught before pdfplumber is invoked)."""
    resp = await client.post(
        "/api/v1/warehouse/invoices/parse-pdf",
        headers=owner_headers,
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 422
    body = resp.json()["detail"]
    assert body["error"] == "empty_pdf"


@pytest.mark.asyncio
async def test_parse_pdf_handles_corrupted_pdf_gracefully(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """Garbage bytes with PDF content-type -> 422 pdf_parse_failed.

    The endpoint catches all parser exceptions and returns a clean 422
    instead of leaking a 500 + pdfplumber traceback to the user.
    """
    resp = await client.post(
        "/api/v1/warehouse/invoices/parse-pdf",
        headers=owner_headers,
        files={"file": ("garbage.pdf", b"%PDF-1.4 this is not really a pdf",
                        "application/pdf")},
    )
    assert resp.status_code == 422
    body = resp.json()["detail"]
    assert body["error"] == "pdf_parse_failed"
