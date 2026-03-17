Datasets — structure & mapping conventions
=========================================

Each dataset lives under `datasets/<dataset>` and follows a small, predictable layout used by the ETL pipeline.

- Layout (per dataset)
--------------------
- `dataset.yaml` — dataset configuration (sources, tables, cleaning settings, manual rename overrides)

Example minimal `dataset.yaml` (cleaning block):

```yaml
dataset:
	id: example_ds
cleaning:
	enabled: true
	method: builtin
	write_mapping: true
```
- `raw/` — original input files (optional)
- `staging/` — staging Parquet tables written by `ingest`
- `processed/` — normalized Parquet tables written by `transform`
- `mappings/` — mapping artifacts used/produced by the pipeline

Important mapping files
-----------------------
- `mappings/clean_columns.yaml` — produced by `ingest` when `cleaning.enabled: true`; persisted when `cleaning.write_mapping` (or `write_mapping`) is enabled; maps raw header -> canonical name
- `mappings/dwc_standard_suggested.yaml` — suggester draft (human-editable)
- `mappings/dwc_suggested_report.yaml` — human-readable suggester report with samples and confidence
- `mappings/dwc_standard.yaml` — approved manual mapping (must reference canonical or processed column names)

Suggester (mapping suggestions)
-------------------------------
The suggester reads headers and sample values from `raw/`, applies fuzzy name matching (RapidFuzz when available, otherwise difflib), numeric/unit heuristics, and any existing clean-column map to propose mappings to standard fields (Darwin Core by default). It writes two artifacts:

- `mappings/dwc_standard_suggested.yaml` — machine-readable draft mapping
- `mappings/dwc_suggested_report.yaml` — human-readable report showing sample values and confidence scores

Run the suggester as part of the draft pipeline:

```bash
make pipeline-draft DATASET=datasets/<dataset>
# Or invoke directly:
PYTHONPATH=. python -m etl.helpers.suggest_mapping --dataset-dir datasets/<dataset> --standard dwc
```

Always review the suggested mapping and the report before promoting to an approved mapping (`mappings/dwc_standard.yaml`).

Per-dataset README
------------------
Add a `datasets/<dataset>/README.md` with dataset-specific notes (data provenance, source licensing, dataset.yaml overrides, and mapping status). A template is available in `datasets/walking_forest/README.md`.
