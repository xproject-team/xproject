"""Barcode and QR code scan logic — decoding, SKU resolution, and server-side validation.

The frontend uses html5-qrcode to capture barcodes; this module handles the
server side: format detection, SKU lookup from the product catalogue, and
audit-trail validation. Supports EAN-13, Code-128, and QR codes.
"""


def decode_barcode(raw: str) -> dict:
    """Parse a raw barcode/QR string and return a structured payload.

    Args:
        raw: The raw string captured by the scanner.

    Returns:
        Dict with keys: format (str), sku (str | None), metadata (dict).

    Raises:
        ValueError: If the barcode format cannot be determined.
    """
    # TODO: implement barcode parsing (EAN-13, Code-128, QR JSON payload)
    return {"format": "unknown", "sku": None, "metadata": {}}


def validate_sku(sku: str) -> bool:
    """Return True if the SKU exists in the product catalogue.

    Always query the database rather than caching, so new SKUs
    are recognised immediately after import.
    """
    # TODO: implement SKU validation against inventory items table
    return True
