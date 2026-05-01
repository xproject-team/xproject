# Slesh API Fixtures

Recorded JSON responses from the real Slesh API, used by the test suite as
a stand-in for the missing sandbox environment.

## Files

| Filename | Endpoint | Recorded |
|---|---|---|
| `brand_my.json` | `GET /brand/my` | 2026-04-29 |
| `shop_my.json` | `GET /shop/my?brandId=...&experienceId=...` | (TODO B2.6) |
| `category_my.json` | `GET /category/my?brandId=...&experienceId=...` | (TODO B2.6) |
| `product_my.json` | `GET /product/my?brandId=...&experienceId=...` | (TODO B2.6) |
| `order_brand_my.json` | `GET /order/brand-my?brandId=...&fromTs=...&toTs=...&pageSize=5` | (TODO B2.6) |

## How to use in tests

```python
def test_my_thing(slesh_fixture):
    raw = slesh_fixture("brand_my")  # returns parsed JSON dict
    brand = Brand.model_validate(raw)
    assert brand.name == "Sundance"
```

The `slesh_fixture` pytest fixture is defined in `backend/tests/conftest.py`.

## How to record a new fixture

When Slesh changes their API, or when we need to capture a new endpoint shape:

1. Make the live API call (e.g. via `curl` or a one-shot Python script)
2. Pretty-print the JSON response
3. Save to `backend/tests/fixtures/slesh/<name>.json`
4. **Redact any sensitive data** before committing — VAT numbers, customer emails,
   phone numbers, full wristband IDs (replace with `wristband_REDACTED_001`, etc.)
5. Update the table above with the recording date and parameters used
6. Commit with message: `test(slesh): record fixture for <endpoint>`

## Privacy note

These files contain real production data from Sundance. Treat them like any
other piece of repo content — they will be in git history forever. Only
fixtures with redacted PII should be committed.
