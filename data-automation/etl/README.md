ETL Module — Architecture & Developer Guide
=========================================

This directory contains the core ETL entrypoints and the helpers package used by the project.

Layout
------
- `ingest.py` — read raw sources, optionally canonicalize column names (controlled by `cleaning.enabled`), write `staging/*.parquet`, and optionally write `mappings/clean_columns.yaml`.
- `transform.py` — normalize/structurize and derive dataset-specific tables, write `processed/*.parquet`.
- `export_standard.py` — apply an approved mapping and export canonical Darwin Core outputs.
- `helpers/` — utility modules for cleaning, suggestion, approval, reconciliation and config validation.

How the pipeline fits together
-----------------------------
1. `ingest` loads raw files (CSV/Excel/vector/etc) and — when `cleaning.enabled` is `true` in the dataset config — applies the canonicalization rules implemented in `helpers/cleaning.py`. `ingest` always writes staging Parquet files; when cleaning is enabled and `cleaning.write_mapping` (or `write_mapping`) is true it also writes a `mappings/clean_columns.yaml` artifact (raw → canonical mapping).
2. `transform` reads staging data, applies domain-normalization rules and writes processed Parquet tables. These processed tables contain the column names produced by `ingest` (canonical when `cleaning.enabled` is true; otherwise the raw header names).
3. `helpers/suggest_mapping.py` can generate `dwc_standard_suggested.yaml` drafts and a human-readable report to assist human reviewers.
4. `helpers/approve_mapping.py` validates a suggested or manual mapping against `processed/*.parquet`, stamps approval metadata, and writes an audited approved mapping.
5. `export_standard` applies the approved mapping and writes canonical Darwin Core outputs.

Developer commands
------------------
From the project root (recommended):

```bash
source data-automation/.venv/bin/activate
export PYTHONPATH=.
make ingest DATASET=datasets/walking_forest
make transform DATASET=datasets/walking_forest
make suggest DATASET=datasets/walking_forest
make approve DATASET=datasets/walking_forest
make export_standard DATASET=datasets/walking_forest
```

Where to look in the code
-------------------------
- Canonicalization rules: `data-automation/etl/helpers/cleaning.py`
- Mapping suggestion: `data-automation/etl/helpers/suggest_mapping.py`
- Mapping approval: `data-automation/etl/helpers/approve_mapping.py`
- Reconciliation helpers: `data-automation/etl/helpers/reconcile_mapping.py`
- Operator & reference docs: `data-automation/etl/docs/exporter.md` (exporter reference) and `data-automation/etl/docs/transform_ops.md` (transform derivations reference)

Testing & extensions
---------------------
- Add unit tests for `helpers/cleaning.py` edge cases (duplicate resolution, unit suffix handling).
- When adding new source formats, update `read_source` in `ingest.py` and provide integration tests under `data-automation/tests/`.
