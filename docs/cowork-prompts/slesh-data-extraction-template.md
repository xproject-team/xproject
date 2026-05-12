# Cowork prompt: Extract Slesh historical Sundance data to CSVs

This template prompt was used for Sundance 2025 (5 event dates,
extracted into `data/sundance-2025/`). Reuse for Sundance 2024
and Sundance 2023 by changing the year references below.

## When to use

Hesam has historical Sundance event data exported from Slesh as
Excel files, organized into folders per event date. Each date
folder contains 8+ subfolders (ricariche, ordini_bracciali,
prodotti, categorie, negozi, operatori, bracciali, utenti,
rimborsi). We want clean CSV extracts staged into
`data/sundance-{YEAR}/` for catalog building + ML training.

## Variables to update before pasting

- {YEAR} — the year (2023, 2024, or 2025)
- {FOLDER_PATH} — the Desktop path (e.g. `Desktop/{YEAR}/SUNDANCE/`)
- Event-date subfolder names will differ per year; let Cowork list them

## The prompt

[PASTE THE FULL PROMPT FROM THE 2025 EXTRACTION — UPDATE THE YEAR REFERENCES]

(Find the full text in commit history; original prompt was used
2026-05-12 for Sundance 2025 extraction. See `data/sundance-2025/`
for the 5 reference CSVs that prompt produced.)

## Verification after Cowork finishes

- 5 CSVs produced: catalog, category_aggregates, stores,
  operator_product_mix, orders_summary
- All 5 share the same `event_date` column in ISO YYYY-MM-DD
- Currency is in euros (decimal), never cents
- PII stripped from orders_summary (no names, emails, user IDs,
  receipt numbers)
- Italian product names preserved verbatim (no translation)

Stage commit pattern:

    mkdir -p data/sundance-{YEAR}
    cp ~/Desktop/{YEAR}/SUNDANCE/_extracted/*.csv data/sundance-{YEAR}/
    git add data/sundance-{YEAR}/
    git commit -m "data: stage Sundance {YEAR} extracted CSVs"
    git push
