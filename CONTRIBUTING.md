Contributing
============

Quick checklist for contributors
--------------------------------
- Run unit tests locally: `python -m pytest data-automation/tests`
- If you modify mapping files under `datasets/**/mappings/**`, run the approver locally to validate the mapping before opening a PR:

```bash
source data-automation/.venv/bin/activate
export PYTHONPATH=.
PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir <dataset> --suggested <your-mapping.yaml>
```

- Keep CI green: the repository includes a mapping validation example in `data-automation/PIPELINE.md` and `.github/workflows/validate-mappings.yml`.

Code style
----------
- Use existing formatting (black/isort) where available. Run linters in CI.

Questions
---------
Open an issue or contact the maintainers listed in `data-automation/README.md`.
