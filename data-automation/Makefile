.PHONY: help ingest transform export_standard metadata validate package run clean clean-all validate-only package-only suggest approve pipeline pipeline-draft pipeline-approved

# Python executable (defaults to project virtualenv)
PYTHON  ?= .venv/bin/python
# Dataset directory relative to project root
DATASET ?= datasets/walking_forest
# Label for package directories / ZIPs
LABEL   ?= latest

help:
	@echo "Targets: help ingest transform export_standard metadata validate package run clean clean-all validate-only package-only suggest approve pipeline"
	@echo "Variables: DATASET=<dataset path> LABEL=<package label> PYTHON=<python interpreter>"


# ---------------------------------------------------------------------------
# Ordered pipeline steps
# ---------------------------------------------------------------------------

ingest:
	$(PYTHON) -m etl.ingest --dataset-dir $(DATASET)

transform: ingest
	$(PYTHON) -m etl.transform --dataset-dir $(DATASET)

export_standard: transform
	$(PYTHON) -m etl.export_standard --dataset-dir $(DATASET)

suggest:
	$(PYTHON) -m etl.helpers.suggest_mapping --dataset-dir $(DATASET)

approve:
	$(PYTHON) -m etl.helpers.approve_mapping --dataset-dir $(DATASET)

pipeline: ingest transform
	@if [ ! -f $(DATASET)/mappings/dwc_standard.yaml ]; then \
echo "No approved mapping found. Run 'make suggest' then 'make approve' (or copy the suggested file to dwc_standard.yaml)"; exit 1; \
	fi
	$(MAKE) export_standard

# Draft pipeline: ingest -> transform -> suggest (emit a standard-style suggested mapping)
pipeline-draft: ingest transform
	$(PYTHON) -m etl.helpers.suggest_mapping --dataset-dir $(DATASET) --emit-standard

# Approved pipeline: ingest -> transform -> validate approved mapping -> export
pipeline-approved: ingest transform
	@if [ ! -f $(DATASET)/mappings/dwc_standard.yaml ]; then \
echo "No approved mapping found at $(DATASET)/mappings/dwc_standard.yaml"; exit 1; \
	fi
	$(PYTHON) -m etl.helpers.approve_mapping --dataset-dir $(DATASET) --mapping $(DATASET)/mappings/dwc_standard.yaml
	$(PYTHON) -m etl.export_standard --dataset-dir $(DATASET)

metadata: export_standard
	$(PYTHON) -m etl.metadata --dataset-dir $(DATASET)

validate: metadata
	$(PYTHON) -m etl.validate --dataset-dir $(DATASET)

package: validate
	$(PYTHON) -m etl.package --dataset-dir $(DATASET) --label $(LABEL)

# Convenience aliases
run: package

validate-only:
	$(PYTHON) -m etl.validate --dataset-dir $(DATASET)

package-only:
	$(PYTHON) -m etl.package --dataset-dir $(DATASET) --label $(LABEL)

# ---------------------------------------------------------------------------
# Clean intermediate outputs for the selected dataset
# ---------------------------------------------------------------------------

clean:
	rm -rf $(DATASET)/staging $(DATASET)/processed $(DATASET)/canonical \
		$(DATASET)/exports $(DATASET)/metadata/qa_report.json

clean-all:
	rm -rf $(DATASET)/staging $(DATASET)/processed $(DATASET)/canonical \
		$(DATASET)/exports $(DATASET)/metadata $(DATASET)/packages \
		$(DATASET)/ro-crate-metadata.json
