walking_forest_demo — quick demo
================================

This minimal example dataset lets you try the pipeline locally without copying a full dataset.

Run the draft pipeline (ingest -> transform -> suggest):

```bash
make pipeline-draft DATASET=examples/walking_forest_demo
```

Expected outputs:
- `examples/walking_forest_demo/staging/demo_table.parquet`
- `examples/walking_forest_demo/mappings/clean_columns.yaml`
- `examples/walking_forest_demo/mappings/dwc_standard_suggested.yaml` (if suggester ran)

Example CSV header (demo/raw/demo.csv)
------------------------------------
```csv
id,Date observed,Species name,Count
```

Expected `mappings/clean_columns.yaml` excerpt (raw -> canonical)
-------------------------------------------------------------
```yaml
"Date observed": observationDate
"Species name": scientificName
```

Notes:
- This dataset uses a single CSV source `raw/demo.csv` and a single table `demo_table`.
- It's intended as a quick smoke-test for contributors; it is not representative of production data.

Walkthrough (step-by-step)
--------------------------
From the repository root:

```bash
# create and activate the pipeline venv (only once)
python -m venv data-automation/.venv
source data-automation/.venv/bin/activate
pip install -r data-automation/requirements.txt
export PYTHONPATH=.

# run the draft pipeline for this example dataset
make pipeline-draft DATASET=examples/walking_forest_demo
```

Inspect outputs under:
- `examples/walking_forest_demo/staging/`
- `examples/walking_forest_demo/mappings/`

To view results in the dashboard (optional):

```bash
R -e "shiny::runApp('data-dashboard', launch.browser=TRUE)"
```
