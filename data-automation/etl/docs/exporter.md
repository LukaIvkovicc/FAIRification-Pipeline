Exporting to community standards
================================

This document explains how to run the standard exporter (`export_standard.py`) to produce community-standard tabular outputs (currently Darwin Core / DwC).

Inputs
- `processed/` (Parquet tables) — produced by `etl/transform.py`.
- `mappings/<key>_standard.yaml` — mapping from processed tables to the target standard (for DwC the key is typically `dwc`, resulting in `mappings/dwc_standard.yaml`).

Running the exporter (Darwin Core / DwC)

```bash
cd data-automation
python3 -m etl.export_standard --dataset-dir datasets/<your_dataset> --standard dwc
```

Important CLI options
- `--processed`: override processed directory (defaults to `<dataset_dir>/processed`).
- `--mapping`: explicit path to mapping YAML (defaults to `<dataset_dir>/mappings/<key>_standard.yaml`, where `<key>` is the normalized standard name, e.g. `dwc`).
- `--out`: output canonical directory (defaults to `<dataset_dir>/canonical`).
- `--csv-dir`: optional directory to also write CSV copies of canonical tables; if not provided the exporter may use `dataset.yaml` or profile defaults (see `outputs.dwc_csv`).
- `--auto-reconcile`: when mapping references missing source columns, attempt a conservative reconciliation against processed column names (uses `mappings/clean_columns.yaml` and fuzzy-matching heuristics).
- `--write-reconciled`: path where the reconciled mapping YAML will be written for inspection (defaults to `<dataset_dir>/mappings/<key>_standard_reconciled.yaml` when `--auto-reconcile` is used).

Quick example — auto-reconcile when export fails:

```bash
python3 -m etl.export_standard --dataset-dir datasets/<your_dataset> --auto-reconcile --write-reconciled datasets/<your_dataset>/mappings/dwc_standard_reconciled.yaml
```

Outputs (DwC)
- `canonical/event.parquet`
- `canonical/occurrence.parquet`
- `canonical/measurement_or_fact.parquet`

Behavior notes & diagnostics
- The exporter performs strict validation: if an approved mapping references processed columns that do not exist, the exporter aborts with a clear diagnostic listing missing tables/columns.
- When `--auto-reconcile` is provided the exporter will attempt conservative replacements and write a reconciled candidate mapping (it will not silently overwrite the approved mapping).
- The exporter selects a sensible default standard using the dataset profile when available; the `--standard` argument overrides this.
- CSV copies are written only when `--csv-dir` is explicitly set or dataset/profile outputs request `dwc_csv`.

Where to look in the code
- Implementation: `etl/export_standard.py` (detailed behavior and flags).
- Related workflow: `data-automation/PIPELINE.md` (runbook and recommended draft→approve→export flow).

Troubleshooting
- If no rows are generated, confirm the approved mapping uses the column names present in `processed/` (these are canonical when `cleaning.enabled` is true during ingest).
- If validation fails, either adjust the mapping to match `processed/` column names, enable/repair `mappings/clean_columns.yaml` and re-run with `--auto-reconcile`, or regenerate a suggested mapping via `make pipeline-draft`.

See also: `data-automation/docs/transform_ops.md` for transform-level derivation guidance.
Exporting to community standards
================================

This document explains how to run the standard exporter (`export_standard.py`) to produce community-standard tabular outputs (currently Darwin Core / DwC).

Inputs
- `processed/` (Parquet tables) — produced by `etl/transform.py`.
- `mappings/<key>_standard.yaml` — mapping from processed tables to the target standard (for DwC the key is typically `dwc`, resulting in `mappings/dwc_standard.yaml`).

Running the exporter (Darwin Core / DwC)

```bash
cd data-automation
python3 -m etl.export_standard --dataset-dir datasets/<your_dataset> --standard dwc
```

Important CLI options
- `--processed`: override processed directory (defaults to `<dataset_dir>/processed`).
- `--mapping`: explicit path to mapping YAML (defaults to `<dataset_dir>/mappings/<key>_standard.yaml`, where `<key>` is the normalized standard name, e.g. `dwc`).
- `--out`: output canonical directory (defaults to `<dataset_dir>/canonical`).
- `--csv-dir`: optional directory to also write CSV copies of canonical tables; if not provided the exporter may use `dataset.yaml` or profile defaults (see `outputs.dwc_csv`).
- `--auto-reconcile`: when mapping references missing source columns, attempt a conservative reconciliation against processed column names (uses `mappings/clean_columns.yaml` and fuzzy-matching heuristics).
- `--write-reconciled`: path where the reconciled mapping YAML will be written for inspection (defaults to `<dataset_dir>/mappings/<key>_standard_reconciled.yaml` when `--auto-reconcile` is used).

Quick example — auto-reconcile when export fails:

```bash
python3 -m etl.export_standard --dataset-dir datasets/<your_dataset> --auto-reconcile --write-reconciled datasets/<your_dataset>/mappings/dwc_standard_reconciled.yaml
```

Outputs (DwC)
- `canonical/event.parquet`
- `canonical/occurrence.parquet`
- `canonical/measurement_or_fact.parquet`

Behavior notes & diagnostics
- The exporter performs strict validation: if an approved mapping references processed columns that do not exist, the exporter aborts with a clear diagnostic listing missing tables/columns.
- When `--auto-reconcile` is provided the exporter will attempt conservative replacements and write a reconciled candidate mapping (it will not silently overwrite the approved mapping).
- The exporter selects a sensible default standard using the dataset profile when available; the `--standard` argument overrides this.
- CSV copies are written only when `--csv-dir` is explicitly set or dataset/profile outputs request `dwc_csv`.

Where to look in the code
- Implementation: `etl/export_standard.py` (detailed behavior and flags).
- Related workflow: `data-automation/PIPELINE.md` (runbook and recommended draft→approve→export flow).

Troubleshooting
- If no rows are generated, confirm the approved mapping uses the column names present in `processed/` (these are canonical when `cleaning.enabled` is true during ingest).
- If validation fails, either adjust the mapping to match `processed/` column names, enable/repair `mappings/clean_columns.yaml` and re-run with `--auto-reconcile`, or regenerate a suggested mapping via `make pipeline-draft`.

See also: `data-automation/docs/transform_ops.md` for transform-level derivation guidance.
