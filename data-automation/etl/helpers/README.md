ETL Helpers — Developer Reference
================================

This file documents the helper modules used by the ETL pipeline. These helpers implement canonicalization (cleaning), mapping suggestion, approval/validation, and conservative reconciliation.

Files & purpose
----------------
- `cleaning.py` — canonicalize column headers. Key function: `build_final_rename_map(raw_cols, manual_overrides, cleaning_enabled, cleaning_method)`.
  - Behavior: when `cleaning.enabled: true` it generates deterministic cleaned names (builtin rules or optional `pyjanitor` path), applies manual `rename` overrides from `dataset.yaml` (overrides win), ensures uniqueness (adds suffixes if needed), and returns a mapping raw->clean.
  - When `cleaning.enabled: false` the auto map is identity and only manual overrides are applied.
  - When ingest runs with `cleaning.write_mapping: true` (or `write_mapping: true`) the helper's output is persisted to `mappings/clean_columns.yaml`.

- `suggest_mapping.py` — generate a draft `dwc_standard_suggested.yaml` plus a human-readable `dwc_suggested_report.yaml`. The suggester prefers canonical column names when a `clean_columns.yaml` is present and annotates suggested output with `meta.column_schema` when appropriate.

- `approve_mapping.py` — validate and stamp approved mappings. Usage:

```
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir <dataset_dir> --suggested <suggested_file> [--force]
```

  - Validates YAML structure and that all referenced `source` columns exist in `processed/` (or `staging/`).
  - Stamps approval metadata (`meta.approved_by`, `meta.approved_at`, `meta.column_schema = "canonical"`) and writes an audit copy to `mappings/history/`.
  - A small heuristic warning was added: if `dataset.yaml` has `cleaning.enabled: false` but the suggested mapping references cleaned-looking names, the approver warns to avoid an accidental mismatch.

- `reconcile_mapping.py` — conservative fuzzy alignment helpers used by the exporter when run with `--auto-reconcile`. It produces a candidate reconciled mapping (e.g. `dwc_standard_reconciled.yaml`) and prints suggested replacements and unresolved names; it never silently overwrites approved mappings.

Running helpers directly
-----------------------
- Suggest mapping (example):

```bash
PYTHONPATH=. python -m etl.helpers.suggest_mapping --dataset-dir datasets/walking_forest
```

- Approve mapping (example):

```bash
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest --suggested datasets/walking_forest/mappings/dwc_standard_suggested.yaml
```

- Reconcile from exporter (example):

```bash
PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest --auto-reconcile --write-reconciled
```

Example suggested mapping snippet (minimal)
------------------------------------------
Use this small example in reviews to understand the expected structure of `dwc_standard_suggested.yaml` or edited drafts.

```yaml
meta:
  dataset: walking_forest
  column_schema: canonical
tables:
  demo_table:
    - source: eventDate
      value: observationDate
```

Notes: the `approve_mapping` helper will validate that each `source` column exists in `processed/` and will stamp approval metadata on promotion.

Developer notes
---------------
- To extend canonicalization rules edit `cleaning.py`. Keep changes deterministic and add unit tests for edge cases (unit suffixes, counts, duplicate resolution).
- The suggester is intentionally conservative for ontology URIs — add manual ontology hints to suggested drafts before approving, or request an enhancement to auto-fill ontology suggestions.
- The approver is the authoritative promotion step. Prefer running it in CI for PRs touching `datasets/**/mappings/**`.

Code references
---------------
- `etl/helpers/cleaning.py` — canonicalization logic
- `etl/helpers/suggest_mapping.py` — suggestion generator
- `etl/helpers/approve_mapping.py` — validation + approval CLI
- `etl/helpers/reconcile_mapping.py` — reconciliation helpers
