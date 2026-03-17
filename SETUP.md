Repository setup — lter-life-labs
================================

Purpose
-------
This file documents repository-level setup and an end-to-end "redo from scratch" set of commands that span the `data-automation` (Python ETL) and `data-dashboard` (R/Shiny) components. Keep component-specific setup inside each component (for example `data-automation/SETUP.md`) and use this top-level file as the canonical operator/developer runbook.

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
-----------------------------------
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

Why keep component-level setup files?
------------------------------------
- This top-level `SETUP.md` gives an operator/developer the steps needed to get the whole repo running.  
- Keep `data-automation/SETUP.md` for component-specific details (Python extras, developer helpers). Keep the dashboard's README for R-specific notes.  
Having both improves discovery and keeps per-component details close to the code.

If you want, I can now:
- run the demo smoke test and report results, or
- expand `data-automation/SETUP.md` with a short troubleshooting matrix and system package lists for Ubuntu/Debian and macOS.
