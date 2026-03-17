Data Automation — ETL Overview
=================================

## Overview
This module contains the core FAIR ETL pipeline used to:
- ingest and canonicalise datasets
- transform and normalise tables
- generate and validate standard mappings
- export FAIR-compliant outputs.
  
Use `PIPELINE.md` for an operator-facing runbook; this README is a compact developer-oriented overview with quick commands and links to helper documentation.

Layout
------
- `etl/` — main pipeline entrypoints (`ingest.py`, `transform.py`, `export_standard.py`) and the `helpers/` package.
- `datasets/` — per-dataset folders containing `dataset.yaml`, `staging/`, `processed/`, and `mappings/`.
- `mappings/` (per-dataset) — mapping artifacts produced/consumed by the pipeline: `clean_columns.yaml`, `dwc_standard_suggested.yaml`, `dwc_standard.yaml`, etc.
- `tests/` — unit & integration tests for ETL components.

Quickstart
----------
From the project root:

```bash
source data-automation/.venv/bin/activate
export PYTHONPATH=.
python -m pip install -r data-automation/requirements.txt
# optional extras used by helpers
python -m pip install pyjanitor rapidfuzz
```

High-level commands
-------------------
- Generate a suggested mapping (ingest -> transform -> suggester):

```bash
make pipeline-draft DATASET=datasets/walking_forest
```

- Run unit tests (from project root):

```bash
pytest -q data-automation/tests
```

- Validate/promote a suggested mapping (approver = audit + validation):

```bash
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest --suggested datasets/walking_forest/mappings/dwc_standard_suggested.yaml
```

- Run the approved export (ingest -> transform -> export):

```bash
make pipeline-approved DATASET=datasets/walking_forest
```

Expected artifacts
------------------
- `datasets/<dataset>/mappings/clean_columns.yaml` — raw -> canonical mapping created by `ingest` when `cleaning.enabled` is true; persisted when `cleaning.write_mapping` (or `write_mapping`) is enabled in the dataset config.
- `datasets/<dataset>/mappings/dwc_standard_suggested.yaml` — suggester draft mapping.
- `datasets/<dataset>/mappings/dwc_standard.yaml` — approved mapping (must reference canonical or processed column names).
 - `datasets/<dataset>/mappings/dwc_standard.yaml` — approved mapping (must reference the column names present in `processed/` — canonical when `cleaning.enabled` is true).
- `datasets/<dataset>/processed/*.parquet` — processed tables used by exporter/approver.

Developer references
--------------------
- Operator runbook: `PIPELINE.md` (user-facing flow and troubleshooting).
- Helpers reference: `etl/helpers/README.md` (developer guide for cleaning, suggester, approver, reconciler).
- Canonicalization rules: `etl/helpers/cleaning.py`

Code pointers (quick)
--------------------
- `etl/ingest.py` — main entry: `main()` and `build_final_rename_map()` in `etl/helpers/cleaning.py`.
- `etl/transform.py` — `main()` and table derivations.
- `etl/export_standard.py` — `main()` and exporter validation/reconcile logic.

Acceptance test (quick)
-----------------------
Generate a draft and check the suggested mapping exists:

```bash
make pipeline-draft DATASET=datasets/walking_forest && test -f datasets/walking_forest/mappings/dwc_standard_suggested.yaml && echo OK
```

Where to go next
-----------------
- For operator guidance and CI examples see `PIPELINE.md`.
- For helper implementation details and how to extend cleaning rules see `etl/helpers/README.md`.
  
data-automation — ETL for LTER datasets
=======================================

Quickstart

1. Create and activate virtual environment (project has `.venv` documented):

```bash
cd data-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the pipeline steps for a dataset (example `walking_forest`):

```bash
# ingest raw -> staging
python3 -m etl.ingest --dataset-dir datasets/walking_forest

# transform staging -> processed
python3 -m etl.transform --dataset-dir datasets/walking_forest

# export processed -> DwC canonical
python3 -m etl.export_standard --dataset-dir datasets/walking_forest --standard dwc
```

Optional mapping suggestion workflow
-----------------------------------

For convenience the repository includes a simple mapping suggester that drafts a DwC mapping you can review and approve before exporting:

```bash
# generate a suggested mapping (draft)
python3 -m etl.helpers.suggest_mapping --dataset-dir datasets/walking_forest

# review datasets/walking_forest/mappings/dwc_standard_suggested.yaml

# approve the suggested mapping (writes mappings/dwc_standard.yaml and an audit copy)
python3 -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest
```

Notes:
- `suggest_mapping` only generates a draft; the pipeline will not use it until you approve and create `dwc_standard.yaml`.
- Use `make suggest` and `make approve` as convenient shortcuts (see Makefile).

Architecture diagram
--------------------

High-level pipeline flow (raw -> canonical -> DwC):

```mermaid
graph LR
	RAW[Raw files (raw/)] --> INGEST[Ingest]
	INGEST --> CLEAN[Optional: Clean columns (mappings/clean_columns.yaml)]
	INGEST --> STAGING[Staging parquet]
	STAGING --> TRANSFORM[Transform]
	TRANSFORM --> PROCESSED[Processed parquet (processed/)]
	PROCESSED --> SUGGEST[Suggest mapping (draft)]
	SUGGEST --> REVIEW[Review & edit draft]
	REVIEW --> APPROVE[Approve mapping (canonical)]
	APPROVE --> EXPORT[Export DwC canonical]
	EXPORT --> METADATA[Generate metadata]
	METADATA --> VALIDATE[Validate]
	VALIDATE --> PACKAGE[Package / publish]
```

Docs
- Transform operation reference: `etl/docs/transform_ops.md`
- Exporter usage: `etl/docs/exporter.md`

Contributing
- Add dataset mappings under `datasets/<name>/mappings/` and dataset YAML under `datasets/<name>/dataset.yaml`.
- Keep transforms conservative and dataset-driven.
