Dataset Profiles
================

Purpose
-------
Dataset profiles define the structural expectations and semantic guidance for different types of ecological datasets used by the FAIR ETL pipeline.

A profile describes how a dataset should be interpreted and processed by the pipeline: which canonical tables are expected, which fields matter, and what mapping targets and validation rules are appropriate. Clear profiles make onboarding new datasets fast and consistent.

Why Profiles?
------------
Ecological datasets vary widely in layout, measurement model, and semantics. Profiles provide a lightweight abstraction so the pipeline can:

- apply consistent transformation rules for similar dataset types
- generate mapping suggestions aligned with expected semantics
- validate dataset structure and report clear diagnostics before export
- support multiple dataset types within a single codebase without ad-hoc logic

Where Profiles Are Used
----------------------
Profiles are referenced from each dataset's `dataset.yaml` using the `profile` key. Example:

```yaml
dataset:
  id: walking_forest
  profile: ecology_plot
```

When the pipeline runs it loads the dataset config and the referenced profile. The profile is used to guide transformation expectations, mapping suggestions, validation checks, and export behavior.

Available Profiles
------------------
The repository contains a small set of profiles (see `data-automation/datasets/profiles/`). Example list:

| Profile file                    | Description                                                       |
| ------------------------------- | ----------------------------------------------------------------- |
| `ecology_plot.yaml`             | Plot-based ecological monitoring datasets (recommended canonical) |
| `ecology.yaml`                  | Alias/shim for `ecology_plot` (kept short-term during migration)  |
| `soil_chemistry.yaml`           | Soil chemistry measurement datasets (draft)                       |
| `sensor_timeseries.yaml`        | Sensor/time-series datasets (draft)                               |
| `spatial_layer.yaml`            | Spatial/geospatial layer expectations (draft)                     |
| `biodiversity.observation.yaml` | Biodiversity observation-style datasets (draft)                   |
| `fair_maturity.yaml`            | FAIR-maturity guidance profile (utility)                          |

Profile Structure
-----------------
Profiles are YAML documents that declare the pipeline-facing contract for a dataset type. Keep them declarative and lightweight.

Typical keys and an illustrative example:

```yaml
profile_id: ecology_plot
title: "Plot-based ecological datasets"
description: "Tidy measurement model for plot- and site-based monitoring"
status: stable   # draft / review / stable / deprecated
aliases: [ecology]
defaults:
  standards:
    data: darwin_core
    metadata: [eml]
cores:
  event:
    required: true
  measurement_or_fact:
    required: true
outputs:
  canonical_tables: [event, measurement_or_fact, occurrence]
validation_rules:
  required_fields:
    event: [eventID, eventDate]
examples:
  - ../../examples/walking_forest_demo
notes:
  - "Recommend ENVO for habitat terms and UO for units."
```

Key parts:
- `profile_id` / `title` / `description` — identity and purpose
- `status` — lifecycle state (draft → review → stable)
- `aliases` — previous names allowed during migration
- `defaults` — recommended standards or exporter defaults
- `cores` / `outputs` — which canonical tables to expect and export
- `validation_rules` — rules the exporter/validator should enforce
- `examples` — one or more example datasets for smoke tests

Pipeline Interaction (high level)
--------------------------------
Profiles influence the pipeline in several non-mutating ways:

- Transformation: profiles declare expected tables and entities so downstream transforms can target the correct outputs.
- Mapping suggestion: the suggester biases its table/field suggestions using profile cores and expected semantics.
- Validation & export: profiles provide validation rules and expected outputs that the exporter and validator use to check completeness and report errors.

Note: profiles are a declarative contract and do not replace or override dataset-local configuration files. The `dataset.yaml` remains the primary dataset configuration.

Adding a New Profile
--------------------
To introduce a new dataset type:

1. Create a new YAML file under `data-automation/datasets/profiles/<profile_id>.yaml`.
2. Populate the required keys (`profile_id`, `title`, `description`, `status`, `cores`, `outputs` and any `validation_rules`).
3. Add one or more example datasets under `examples/` and reference them in `examples:` in the profile.
4. Add a smoke test under `data-automation/tests/` that runs the draft pipeline for the example dataset and asserts expected artifacts.
5. Open a PR describing the intended scope, add reviewers, and run CI smoke tests.

Design Principles
-----------------
- Lightweight: profiles should be short, human-readable, and focused on structure and semantics.
- Declarative: avoid encoding dataset-specific logic inside the profile; keep logic in pipeline code.
- Extensible: allow optional `validation_rules` and `notes` to grow the contract without breaking stable profiles.

Quick diagram
-------------
```
dataset.yaml
    │
    ˇ
  profile.yaml
    │
    ˇ
 pipeline stages -> suggest -> transform -> validate -> export
```

PR checklist for profile changes
--------------------------------
- Ensure `profile_id` matches the filename.
- Add or update `examples:` and confirm the example runs locally with `make pipeline-draft`.
- Add/adjust smoke tests in `data-automation/tests/` for any new validation rules.
- If consolidating names, add `aliases:` and document the migration plan in the PR.

Where to get help
-----------------
If unsure about modeling a dataset type or mapping hints, open an issue or request a short pairing review. Profiles are central to onboarding and it’s worth a quick discussion.


