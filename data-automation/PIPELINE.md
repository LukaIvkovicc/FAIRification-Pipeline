Pipeline auto clean and suggestion mapping
— Suggest → Review → Approve → Export

This file documents the recommended workflow for generating, reviewing, and using suggested mappings, and for running the pipeline end-to-end.

See the ETL overview: [data-automation/README.md](data-automation/README.md)
Root README: [README.md](../README.md)
Operator reference: [data-automation/etl/docs/exporter.md](data-automation/etl/docs/exporter.md) — exporter CLI and reconciliation; [data-automation/etl/docs/transform_ops.md](data-automation/etl/docs/transform_ops.md) — transform derivations reference.

Contents
- Quick setup
- Draft pipeline (suggest)
- Outputs to inspect
- Review & edit
- Validate approved mapping
- Conservative reconciliation
- Approved pipeline (export)
- Troubleshooting
- Automation & CI
- Canonicalization & Reconciliation

Principles
- Approved mappings must reference the column names present in `processed/*.parquet` (typically canonical when `cleaning.enabled` is true).
- Suggested mappings (drafts) may contain provenance and `_etl_` fields; keep those out of the approved mapping.
- Use the suggester for human-in-the-loop suggestions; use the reconciler only for conservative automated fixes.

Quick setup
1. From the project root:

```bash
source .venv/bin/activate
export PYTHONPATH=.
```

Dependencies
- Install runtime dependencies used by the pipeline (run from project root):

```bash
python -m pip install -r data-automation/requirements.txt
# optional extras: pyjanitor, rapidfuzz
python -m pip install pyjanitor rapidfuzz
```

Draft pipeline (suggest)
- Runs ingest, transform, then suggester and writes a standard-style suggested mapping.

```bash
make pipeline-draft DATASET=datasets/walking_forest
```

Suggester (mapping suggestions)
-------------------------------
The suggester reads headers and sample values from `raw/`, applies fuzzy name matching (RapidFuzz when available, otherwise difflib), numeric/unit heuristics, and any existing clean-column map to propose mappings to standard fields (Darwin Core by default). It writes two primary artifacts alongside the dataset:

- `mappings/dwc_standard_suggested.yaml` — machine-readable draft mapping
- `mappings/dwc_suggested_report.yaml` — human-readable report showing sample values and confidence scores

Run the suggester as part of the draft pipeline or directly:

```bash
make pipeline-draft DATASET=datasets/<dataset>
# or invoke directly:
PYTHONPATH=. python -m etl.helpers.suggest_mapping --dataset-dir datasets/<dataset> --standard dwc
```

Always review the suggested mapping and the report before promoting to an approved mapping (`mappings/dwc_standard.yaml`).

Outputs to inspect
- Suggested mapping (per-table + canonical draft):
  - datasets/<dataset>/mappings/dwc_standard_suggested.yaml
- Human-readable report:
  - datasets/<dataset>/mappings/dwc_suggested_report.yaml
- Clean-columns mapping (from ingest):
  - datasets/<dataset>/mappings/clean_columns.yaml

Expected artifacts (after a successful draft → approve → export run)
-- `datasets/<dataset>/mappings/clean_columns.yaml` (raw -> canonical mapping; present when `cleaning.enabled` is true and `write_mapping` is enabled)
- `datasets/<dataset>/mappings/dwc_standard_suggested.yaml` (draft)
- `datasets/<dataset>/mappings/dwc_suggested_report.yaml` (human report)
- `datasets/<dataset>/mappings/dwc_standard.yaml` (approved, meta.column_schema = "canonical")
- `datasets/<dataset>/processed/*.parquet` — processed tables (contain canonical column names when `cleaning.enabled` is true)
- canonical/exported DwC outputs (check your dataset's export destination)

See the canonicalization rules in `etl/helpers/cleaning.py` for exactly how cleaned names are generated and de-duplicated.
  
Acceptance test (quick)
```bash
make pipeline-draft DATASET=datasets/walking_forest && test -f datasets/walking_forest/mappings/dwc_standard_suggested.yaml && echo OK
```
Example cleaning config (in `dataset.yaml`):
```yaml
# dataset.yaml
cleaning: {enabled: true, method: "builtin", write_mapping: true}
```

Review & edit (manual step)
- Open the suggested mapping and the report. Create/update the approved mapping at:
  - datasets/<dataset>/mappings/dwc_standard.yaml
- Rules for approved mapping edits:
  - Use the column names present in `processed/` (these are canonical when `cleaning.enabled` is true).
  - Remove ETL-only provenance fields (leading `_etl_` columns) from the approved mapping.
  - When the mapping uses canonical names, add `meta.column_schema: "canonical"` (the approver will stamp this on promotion).
- Always keep a backup before editing:

```bash
cp datasets/walking_forest/mappings/dwc_standard.yaml datasets/walking_forest/mappings/dwc_standard.yaml.bak
```

Validate approved mapping (fast-fail)
- Run the approval/validation helper to ensure the approved mapping references actual processed columns:

```bash
make approve DATASET=datasets/walking_forest
# or directly
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest --mapping datasets/walking_forest/mappings/dwc_standard.yaml
```

Conservative reconciliation (optional)
- If validation fails and you want automated, conservative suggestions:

```bash
PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest --auto-reconcile --write-reconciled
```

- Inspect: datasets/walking_forest/mappings/dwc_standard_reconciled.yaml
- Use it as guidance; apply minimal manual fixes to the approved mapping.

Approved pipeline (export)
- Run ingest/transform, validate the approved mapping, then export canonical DwC outputs:

```bash
make pipeline-approved DATASET=datasets/walking_forest
```

Troubleshooting
- If export aborts, read the diagnostics: exporter prints per-table missing canonical columns.
- Fix either `mappings/dwc_standard.yaml` or, if the canonical mapping is wrong, adjust `mappings/clean_columns.yaml` and re-run `make pipeline-draft`.

Automation & CI
- Recommended CI checks:
  - On PRs modifying `mappings/dwc_standard.yaml`, run `etl.helpers.approve_mapping` to fail the PR if the approved mapping references missing canonical columns.
  - Nightly job: run the suggester and surface diffs to detect schema drift early.

Example GitHub Actions workflow (validate mapping changes)

```yaml
# .github/workflows/validate-mappings.yml
name: Validate mappings
on:
  pull_request:
    paths:
      - 'datasets/**/mappings/**'

jobs:
  validate-mappings:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - name: Install dependencies
        run: python -m pip install -r data-automation/requirements.txt
      - name: Find changed mapping files and validate
        run: |
          set -euo pipefail
          git fetch origin ${{ github.event.pull_request.base.ref }} --depth=1 || true
          CHANGED=$(git diff --name-only origin/${{ github.event.pull_request.base.ref }}...HEAD | grep 'datasets/.*/mappings/.*\.ya\?ml' || true)
          if [ -z "$CHANGED" ]; then echo "No mapping changes"; exit 0; fi
          for f in $CHANGED; do
            ds=$(dirname $(dirname "$f"))
            echo "Validating $f (dataset $ds)"
            PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir "$ds" --suggested "$f" || exit 1
          done
```

Notes: this example runs `approve_mapping` against changed mapping files; it may produce audit copies in the CI workspace but will fail the job if validation fails.

Canonicalization & Reconciliation

- When reconcile runs: Reconciliation is optional and only runs when explicitly requested (for example via the exporter `--auto-reconcile` flag or by invoking the reconciler helper). Typical flow: exporter aborts because the approved mapping references columns not present in `processed/`; re-run export with `--auto-reconcile --write-reconciled` to produce a conservative `*_reconciled.yaml` candidate for review. Reconcile never silently replaces an approved mapping — it writes a reconciled candidate and prints suggested replacements and unresolved names for manual review.

- How ingest builds and applies renames: ingest calls `build_final_rename_map(raw_cols, manual_overrides, cleaning_enabled, cleaning_method)` (see `etl/helpers/cleaning.py`). If `cleaning.enabled` is `true` (default) the function auto-generates cleaned/canonical names (builtin or `pyjanitor` path) and then applies manual overrides (manual `rename` entries win). If `cleaning.enabled` is `false` the auto-clean map is identity (raw -> raw) and only manual overrides are applied. The function enforces uniqueness (duplicates get suffixes) and `ingest` applies the final map with `df = df.rename(columns=final_map)`. When enabled, `ingest` writes `mappings/clean_columns.yaml` (raw -> canonical) if `write_mapping` is true.

- How downstream steps use renamed columns: all downstream steps (transform, processed tables, suggester, exporter, approver) operate on the column names produced by `ingest`. `transform` reads staging Parquet (final names) and writes processed Parquet (same final names or derived columns). The `approver` validates mapping `source` names against what's present in `processed/` — therefore approved mappings must use the cleaned/canonical names when `cleaning.enabled: true`.

- What if cleaning/renaming is disabled or you prefer raw names: when `cleaning.enabled: false` ingest does not alter header names (unless you supply manual `rename` overrides). The pipeline will still work: processed/staging Parquet will contain the original raw names and mapping files must reference those raw names. If an approved mapping expects cleaned names but cleaning is disabled, the `approver` and `exporter` will fail with missing-column diagnostics; fix by enabling cleaning, updating the mapping to raw names, or running reconciliation to generate candidate fixes and then reviewing them.

- Recommendations & commands:
  - Default: keep `cleaning.enabled: true` so the pipeline produces deterministic canonical names and a `clean_columns.yaml` artifact for downstream consumers.
  - If export fails due to missing columns, try conservative reconciliation first and inspect the candidate file:

```bash
PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest --auto-reconcile --write-reconciled
```

  - Promote an edited suggested draft (validate + audit):

```bash
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest --suggested datasets/walking_forest/mappings/dwc_standard_suggested.yaml
```

  - Generate a draft suggestion (ingest + transform + suggester):

```bash
make pipeline-draft DATASET=datasets/walking_forest
```

These notes explain when reconcile runs, how rename decisions are made by `ingest`, how downstream steps consume those names, and what to do when cleaning is disabled.

Notes
- Always run commands from the project root with `PYTHONPATH=.`, so `python -m etl.*` works reliably.
- Keep provenance (`original_source`, `_etl_...`) in draft files only; the approved mapping should be a clean contract for downstream users.

Contact
- If unsure about a suggested mapping entry, prefer human review; ask a domain expert to confirm ambiguous measurementType/unit choices.


##
Yes — exactly. Two supported, interoperable flows:

Option A — Manual approved mapping (expert)

You create/edit datasets/<ds>/mappings/dwc_standard.yaml yourself.
Best practice: validate & stamp it with the approver (creates audit copy):

PYTHONPATH=. python -m etl.helpers.approve_mapping \
  --dataset-dir datasets/walking_forest \
  --suggested datasets/walking_forest/mappings/dwc_standard.yaml --force

Then run the export/pipeline as usual:

PYTHONPATH=. python -m etl.ingest --dataset-dir datasets/walking_forest
PYTHONPATH=. python -m etl.transform --dataset-dir datasets/walking_forest
PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest


Option B — Draft → Review → Promote (recommended for new users)

Generate a draft suggestion:

make pipeline-draft DATASET=datasets/walking_forest
# writes datasets/walking_forest/mappings/dwc_standard_suggested.yaml

Edit/review the suggested file (dwc_standard_suggested.yaml) as needed.
Promote the suggested file to an approved mapping (approver validates canonical columns and writes audit copy):

PYTHONPATH=. python -m etl.helpers.approve_mapping \
  --dataset-dir datasets/walking_forest \
  --suggested datasets/walking_forest/mappings/dwc_standard_suggested.yaml

Then run export (same commands as above).
Notes and rules

The approver is the canonical promotion step — use it rather than blindly copying files. It:
Validates that source columns exist in processed/ (fails fast with diagnostics).
Stamps meta.approved_by, meta.approved_at, and meta.column_schema = "canonical".
Writes an audit copy under mappings/history/.
If you edit an existing approved mapping, re-run the approver with --suggested <edited-file> and --force to validate and record the change.
make pipeline-draft and make pipeline-approved are the convenience targets; the approver call is the authoritative, auditable promotion.



Details

The pipeline will use an existing approved mapping file (e.g. the approved mapping at datasets/walking_forest/mappings/dwc_standard.yaml) if present; you can run export directly without calling the approver.
However, run etl.helpers.approve_mapping when you (or a collaborator) promote or change a mapping because it:
Validates that all source columns exist in processed/ (prevents silent bad exports),
Stamps audit metadata (meta.approved_by, meta.approved_at, meta.column_schema = "canonical"),
Writes an audit copy under mappings/history/.
Commands (pick one)

Use your manual mapping and validate+export (recommended):


PYTHONPATH=. python -m etl.helpers.approve_mapping \
  --dataset-dir datasets/walking_forest \
  --suggested datasets/walking_forest/mappings/dwc_standard.yaml --force

PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest


Promote a suggested draft (draft → approve → export):

make pipeline-draft DATASET=datasets/walking_forest
# review/edit dwc_standard_suggested.yaml
PYTHONPATH=. python -m etl.helpers.approve_mapping \
  --dataset-dir datasets/walking_forest \
  --suggested datasets/walking_forest/mappings/dwc_standard_suggested.yaml

make pipeline-approved DATASET=datasets/walking_forest


Skip approver (not recommended): run exporter directly

PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest

(Exporter will still validate and abort with diagnostics if columns are missing.)

Recommendation

Always run the approver when promoting or editing a mapping (use --force when replacing an existing approved file). Enforce this in CI for PRs that touch mappings/ to keep exports deterministic and auditable.


#####

Quick Summary — two ways to use the pipeline: (A) expert/manual mapping (you provide dwc_standard.yaml) or (B) assisted mapping (pipeline generates dwc_standard_suggested.yaml, you review/edit, then promote with the approver). Always validate promotions with the approver for safety and auditability.

New dataset (full guidnance)

Ingest + transform:
make ingest DATASET=datasets/walking_forest then make transform DATASET=datasets/walking_forest
Generate draft (optional/helpful for new users):
make pipeline-draft DATASET=datasets/walking_forest
Produces: datasets/walking_forest/mappings/dwc_standard_suggested.yaml and report datasets/walking_forest/mappings/dwc_suggested_report.yaml.
Review & edit: open the suggested YAML, check original_source + samples, edit measurementType/unit or add ontology URIs if wanted.
Promote (validate + audit):
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir datasets/walking_forest --suggested datasets/walking_forest/mappings/dwc_standard_suggested.yaml
This validates that all source columns exist in processed/, stamps meta.approved_by/approved_at/column_schema, and writes an audit copy.
Export canonical DwC:
make pipeline-approved DATASET=datasets/walking_forest (or PYTHONPATH=. python -m etl.export_standard --dataset-dir datasets/walking_forest).
If you already have a manual mapping

Place or edit the approved mapping at datasets/<ds>/mappings/dwc_standard.yaml.
Run the approver to validate & record the change:
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir <dataset> --suggested <path-to-your-dwc_standard.yaml> --force
Then run export as above.
When you change mappings later

Always run the approver after edits (use --force to overwrite existing approved mapping). This prevents silent bad exports and keeps an audit trail.
When export fails for missing columns

Run conservative reconciliation to get suggested fixes:
PYTHONPATH=. python -m etl.export_standard --dataset-dir <dataset> --auto-reconcile --write-reconciled <dataset>/mappings/dwc_standard_reconciled.yaml
Inspect *_reconciled.yaml, fix unresolved items manually, then run the approver to promote.
Ontology notes

Suggested drafts currently include human-readable measurementType/unit but not automatic ontology URIs (ontology_annotations is empty). Add URIs manually to the suggested file before approving, or I can add an ontology-hint feature to the suggester if you want.
CI / policy (recommended)

Require the approver/validation job in PR checks for any changes to datasets/**/mappings/** so mapping promotions are validated and auditable before merge.