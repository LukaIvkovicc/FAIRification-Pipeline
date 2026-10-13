# FAIR Ecological Data Pipeline and Dashboard

[![status](https://img.shields.io/badge/status-experimental-orange)](#) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![docs](https://img.shields.io/badge/docs-available-brightgreen)](#)

A modular FAIRification pipeline and dashboard for transforming heterogeneous ecological monitoring datasets into FAIR (Findable, Accessible, Interoperable, Reusable) research objects.


This repository provides:

- a Python-based ETL pipeline for dataset FAIRification, preparation and standardisation
- a companion R/Shiny dashboard for communicating FAIR progress (interactive review and guidance on FAIR)
#

## Metadata files

The pipeline produces and version-controls several metadata files to ensure reproducibility, provenance, and FAIR compliance:

- `dataset_metadata.json` — machine-readable dataset-level metadata
- `metadata.jsonld` — JSON-LD for semantic web interoperability
- `ro-crate-metadata.json` — RO-Crate metadata for packaging and sharing research objects
- `manifest.json` — describes files and structure in a dataset package
- `eml_draft.xml` — Ecological Metadata Language draft for further curation
- `qa_report.json` — quality assurance/validation report
- `walking_forest_metadata.yaml` — example YAML metadata for a demo dataset

These files are versioned in git to support transparent, reproducible, and auditable data FAIRification. Do not remove them from version control.

## .gitignore and generated outputs

All generated outputs (build artifacts, intermediate files, packages, etc.) are ignored by git for reproducibility and repository cleanliness. See the `.gitignore` file for details.

---

## Documentation

| Guide                                                                                        | Description            |
| -------------------------------------------------------------------------------------------- | ---------------------- |
| [`data-automation/README.md`](data-automation/README.md)                                     | FAIRification pipeline overview  |
| [`data-automation/PIPELINE.md`](data-automation/PIPELINE.md)                                 | Operator runbook       |
| [`data-automation/datasets/profiles/README.md`](data-automation/datasets/profiles/README.md) | Dataset profile system |
| [`data-automation/dataset_author_guide.md`](data-automation/dataset_author_guide.md)         | Adding new datasets    |
| [`data-dashboard/README.md`](data-dashboard/README.md)                                       | Dashboard usage        |
| [`docs/architecture.md`](docs/architecture.md)                                               | System architecture    |

---

## Overview

The repository contains two independent but complementary components:

| Component           | Description                                                                                              |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| **data-automation** | Python FAIRification ("ETL") pipeline for ingesting, structuring, mapping to standards, validating, and exporting datasets |
| **data-dashboard**  | R/Shiny application for inspecting datasets and reviewing pipeline outputs                               |

The dashboard enhances usability but is **not required** to run the pipeline.

## At-a-glance (recommended workflow)

1. Ingest & canonicalise raw files: `make ingest` (or `make pipeline-draft`)
2. Transform & normalise tables: `make transform`
3. Draft mapping suggestions: `make suggest` (review suggested mapping in `$(DATASET)/mappings/`)
4. Approve mapping: `make approve` or copy the reviewed mapping to `$(DATASET)/mappings/dwc_standard.yaml`
5. Export standard outputs: `make export_standard` or `make pipeline-approved`
6. Produce metadata, validate and package: `make metadata && make validate && make package`

These targets are defined in `data-automation/Makefile` and are safe to run from the repository root.

---

## Pipeline Workflow

This repository implements the full ETL (Extract-Transform-Load) workflow to FAIRify a dataset. Typical steps:

1. Ingest — read raw files, clean headers and canonicalise input tables (create `staging/` and canonical tables).
2. Transform — normalise tables, apply cleaning rules and derive fields (`processed/` / `canonical/`).
3. Suggest mapping — generate a draft Darwin Core mapping YAML from canonical tables (`make suggest`).
4. Review & approve mapping — review the suggested mapping and save the approved file to `mappings/dwc_standard.yaml`.
5. Export — produce Darwin Core (and other) standard outputs from the approved mapping (`make export_standard`).
6. Metadata - generate metadata draft (EML_draft.xml) + instructions for further curation (ezEML generator)
7. validate & package — run validation (Q/A report), and package the dataset containing `advanced` and `publication` folders for user inspection prior publication (`make metadata && make validate && make package`).

You can run the draft flow (ingest → transform → suggest) with:
```bash
make pipeline-draft DATASET=<path/to/dataset>
```
and the approved flow (ingest → transform → approve → export) with:
```bash
make pipeline-approved DATASET=<path/to/dataset>
```

Automation + human review: the pipeline combines automated suggestion/generation with manual review steps (mapping approval and QA).

---

## Repository Structure

- `data-automation/` — core FAIR ETL pipeline (Python)
- `data-dashboard/` — interactive Shiny dashboard (R)
- `examples/` — minimal demonstration datasets
- `docs/` — architecture and design documentation

Key modules:

- ETL logic → `data-automation/etl/`
- Dataset configuration → `data-automation/datasets/` (per-dataset folders with `mappings/`, `raw/`, `staging/`, ...)
- Profile configuration → `data-automation/datasets/profiles/`

### Mapping files and generated outputs

- Approved mapping used by the approved pipeline: `mappings/dwc_standard.yaml` (per-dataset)
- Suggested mappings are produced by `make suggest` and appear in the dataset `mappings/` directory for review

Generated outputs (build artifacts — ignored by git):

- `staging/`, `processed/`, `canonical/` — intermediate and canonical tables
- `exports/` — exported Darwin Core / standard outputs
- `metadata/` — QA reports and metadata artifacts
- `packages/` — packaged dataset archives
- `ro-crate-metadata.json` — RO-Crate metadata (when created)

Use `make clean` or `make clean-all` to remove generated outputs for the selected dataset.

---

## Common Tasks

| Task                 | Command                                                                  |
| -------------------- | ------------------------------------------------------------------------ |
| Run pipeline (draft) | `make pipeline-draft DATASET=data-automation/datasets/walking_forest`    |
| Run full pipeline    | `make pipeline-approved DATASET=data-automation/datasets/walking_forest` |
| Suggest mapping      | `make suggest DATASET=data-automation/datasets/walking_forest`           |
| Approve mapping      | `make approve DATASET=data-automation/datasets/walking_forest`           |
| Run dashboard        | `R -e "shiny::runApp('data-dashboard', launch.browser=TRUE)"`            |
| Run tests            | `pytest data-automation/tests`                                           |

### Makefile variables (examples)

- `DATASET` — dataset path (default: `datasets/walking_forest`)
- `PYTHON` — Python interpreter used by Makefile (default: `.venv/bin/python`)
- `LABEL` — label used when packaging (default: `latest`)

Examples:

```bash
# use a specific interpreter
make pipeline-draft DATASET=data-automation/datasets/walking_forest PYTHON=.venv/bin/python

# create a package with a label
make package DATASET=data-automation/datasets/walking_forest LABEL=v1.0
```

---

### Getting Started ### 

## Repository setup - FAIRification-Pipeline
===============================================

Prerequisites (high level)
--------------------------
- Git (clone the repository)
- Python 3.8+ and `venv` or a supported Conda/pyenv environment
- pip and build tools for Python packages (`build-essential`, `python3-dev` on Debian/Ubuntu)
- R (4.0+) for the dashboard component and the `shiny` ecosystem
- Optional: Docker (for containerized runs)

Quick clone and prepare (recommended)
-----------------------------------
Replace `<repo-url>` with your repository HTTPS or SSH URL.

```bash
git clone <repo-url>
cd lter-life-labs
```

Set up the Python ETL environment (data-automation)

```bash
cd data-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional extras used by helpers
pip install pyjanitor rapidfuzz pyarrow polars
cd ..
```

Set up the R dashboard environment

```r
# in an R console or Rscript
install.packages(c('shiny','dplyr','ggplot2','readr','DT'))
```

Or use Docker to run the dashboard (optional)

```bash
# Example: build and run a lightweight R/shiny container (high-level)
# docker build -t lter-dashboard data-dashboard/
# docker run --rm -p 8080:3838 lter-dashboard
```

End-to-end smoke test (demo dataset)
------------------------------------
This quick run demonstrates a full draft → approve → export workflow using the included demo dataset.

```bash
# from repository root
cd data-automation
source .venv/bin/activate
make pipeline-draft DATASET=examples/walking_forest_demo
# inspect outputs under examples/walking_forest_demo/mappings and staging
make pipeline-approved DATASET=examples/walking_forest_demo
```

Run the dashboard locally
-------------------------
From the repository root you can start the dashboard (after installing R packages):

```bash
Rscript -e "shiny::runApp('data-dashboard', port=8080, host='0.0.0.0')"
```

Recreating (redo) the entire pipeline from scratch
-------------------------------------------------
To reset and re-run the pipeline safely for a dataset:

1. Remove generated artifacts for the dataset (safe, targeted):

```bash
# example: remove processed/staging/mappings for a dataset
rm -rf datasets/<dataset>/staging datasets/<dataset>/processed datasets/<dataset>/mappings/*.yaml
```

2. Re-run ingest/transform/suggest/approve/export (example):

```bash
cd data-automation
source .venv/bin/activate
make pipeline-draft DATASET=datasets/<dataset>
# review suggested mapping and edit as needed
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/<dataset> --suggested datasets/<dataset>/mappings/dwc_standard_suggested.yaml
make pipeline-approved DATASET=datasets/<dataset>
```

Notes & troubleshooting
----------------------
- If `pip install` fails for performance-sensitive packages (pyarrow/polars) on Linux, install the system build deps first (Debian/Ubuntu: `sudo apt-get install -y build-essential python3-dev libpq-dev` and relevant compression libs).  
- If the dashboard fails to start, verify R packages are installed and check `R` output for missing system libs.  
- The `approver` will validate mappings against `processed/` column names; if you disable cleaning (`cleaning.enabled: false`) approved mappings must use raw header names.


### Prerequisites

- Python 3.10+ (recommended)
- For geospatial workflows (geopandas, GDAL, PROJ) we strongly recommend using `conda`/`mamba` with the `conda-forge` channel for reproducible system dependencies.

### Recommended (conda-forge, best for geospatial stacks)

```bash
conda create -n fairify python=3.10 -c conda-forge -y
conda activate fairify
# install system/geospatial packages via conda when needed, then install Python deps
pip install -r data-automation/requirements.txt
```

### Simple (venv + pip)

```bash
python -m venv data-automation/.venv
source data-automation/.venv/bin/activate
pip install -r data-automation/requirements.txt
export PYTHONPATH=.
```

### Notes

- If you use the geospatial features (e.g., `geopandas`), prefer conda-forge to avoid compilation/system library issues.
- An authoritative pinned requirements file is available at [data-automation/requirements.txt](data-automation/requirements.txt).

If you want a fully reproducible system-spec, consider adding an `environment.yml` (conda) or a `Dockerfile` describing GDAL/PROJ system dependencies.

## Quick Start

### Run the pipeline (example)

Create a Python environment and install dependencies (see above for conda recommendation):

```bash
python -m venv data-automation/.venv
source data-automation/.venv/bin/activate
pip install -r data-automation/requirements.txt
export PYTHONPATH=.
```

Run the example dataset pipeline:

```bash
make pipeline-draft DATASET=data-automation/datasets/walking_forest
```

See full operator instructions in `data-automation/PIPELINE.md`.

### Run the dashboard

Install required R packages and launch the app:

```bash
R -e "install.packages(c('shiny','shinythemes','dplyr'))"
R -e "shiny::runApp('data-dashboard', launch.browser=TRUE)"
```

### Example dataset

A minimal demonstration dataset is provided at `examples/walking_forest_demo` — it illustrates the full workflow from raw input to standardised output.

## Project status

Prototype research infrastructure developed within the LTER-LIFE project.

Current focus: FAIR data preparation workflows, reproducible mapping, and ecological dataset interoperability.

## Testing & linting

Run tests and format/lint the code:

```bash
pytest data-automation/tests
black .
flake8 .
isort .
```

## Contributing

See `CONTRIBUTING.md` for contribution guidelines, coding style and tests. Run tests locally before opening PRs.

## Maintainer

Luka Ivkovic — Utrecht University / LTER-LIFE / NIOO-KNAW

## License & citation


## License

**A LICENSE file is not yet present.**
add an open license such as MIT or Apache-2.0 to the project root. If you publish results based on the pipeline, include a short citation or acknowledgement in dataset metadata.

---
