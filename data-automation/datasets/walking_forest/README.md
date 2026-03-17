# Walking Forest — dataset README

This folder contains the Walking Forest dataset used in the FAIRification walkthrough and examples.

Overview
--------
- Short id: `walking_forest_2025` (see `dataset.yaml`).
- Topic: oak regeneration monitoring (plot-level observations and measurements).
- Purpose: example dataset used to demonstrate the draft → review → approve → export workflow.

Important files & directories
-----------------------------
- `dataset.yaml` — dataset configuration (sources, tables, derivations, `cleaning` settings).
- `raw/` — original source files (Excel/CSV/etc.).
- `staging/` — ingest output (Parquet tables after header canonicalization/renames).
- `processed/` — transform output (final canonical tables used by exporter).
- `mappings/` — mapping artifacts (suggested, approved, reconciled) including `clean_columns.yaml` when produced.
- `exports/` and `canonical/` — exporter output (DwC canonical tables).

Quick commands
--------------
From the project root (recommended):

```bash
# generate draft suggestion (ingest + transform + suggest)
make pipeline-draft DATASET=datasets/walking_forest

# validate an approved mapping (approver stamps audit metadata)
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest --suggested datasets/walking_forest/mappings/dwc_standard.yaml

# run full approved export
make pipeline-approved DATASET=datasets/walking_forest
```

Notes for authors & operators
----------------------------
- `cleaning.enabled` in `dataset.yaml` controls whether ingest canonicalizes column names. When `true`, `processed/` contains canonical names and approved mappings must reference those canonical names.
- If `cleaning.enabled: false`, mappings should reference the raw header names found in `processed/`.
- If export fails due to missing mapping columns, try conservative reconciliation:

```bash
PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest --auto-reconcile --write-reconciled datasets/walking_forest/mappings/dwc_standard_reconciled.yaml
```

References
----------
- Dataset author guidance: `data-automation/dataset_author_guide.md`
- Pipeline runbook: `data-automation/PIPELINE.md`
- ETL operator docs: `data-automation/etl/docs/exporter.md` and `data-automation/etl/docs/transform_ops.md`

If you need a quick demo package for the dashboard, copy or symlink this dataset's publication package into `data-dashboard/fair_packages/`.

walking_forest — dataset notes (template)
=======================================


Dataset summary
---------------
- Common name: walking_forest
- Source files: describe where raw files came from and any licensing or contact info.

- Important dataset.yaml settings
-------------------------------
- `cleaning.enabled`: true  # recommended (produces canonical names). Set `cleaning.write_mapping: true` to persist `mappings/clean_columns.yaml` (raw -> canonical) if you want the artifact saved.
- `cleaning.method`: "builtin" # or "pyjanitor" if you have that dependency
- Manual rename overrides: list under `tables.<table>.rename` if needed

Current mapping status (example)
--------------------------------
- `mappings/dwc_standard_suggested.yaml`: draft (review needed)
- `mappings/dwc_standard.yaml`: approved (if present)

Example `cleaning` block for `dataset.yaml`:

```yaml
cleaning:
	enabled: true
	method: builtin
	write_mapping: true
```

How to run for this dataset
---------------------------
Generate draft suggestion (ingest -> transform -> suggester):

```bash
make pipeline-draft DATASET=datasets/walking_forest
```

Validate & promote suggested mapping:

```bash
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest --suggested datasets/walking_forest/mappings/dwc_standard_suggested.yaml
```

Export canonical DwC:

```bash
make pipeline-approved DATASET=datasets/walking_forest
```

Mapping status
--------------
- `mappings/dwc_standard_suggested.yaml`: draft (review needed)
- `mappings/dwc_standard.yaml`: approved (if present)

Notes & TODO
-----------
- Add notes about any special column renames or manual QA steps.


