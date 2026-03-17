# Dataset Author Guide: `dataset.yaml` and Mappings

This guide explains how dataset authors should fill in `dataset.yaml` and the standard mapping files (e.g. `mappings/dwc_standard.yaml`) without writing code.

## 1. `dataset.yaml`: Describe your dataset

`dataset.yaml` lives in `datasets/<your_dataset>/dataset.yaml` and answers three questions:

- What is this dataset? (`dataset` block)
- Where do the source files live? (`sources` block)
- How do source tables/sheets become canonical tables? (`tables` + `derivations`)

### 1.1 `dataset` block

```yaml
dataset:
  id: walking_forest_2025
  title: "Oak regeneration in rewilding floodplain the Millingerwaard"
  profile: ecology_plot
```

- `id`: short, stable identifier for the dataset (used in manifests, RO-Crate, QA).
- `title`: human-readable title.
- `profile`: which pipeline profile to use (e.g. `ecology_plot`). This controls standards (DwC, EML, etc.) and some validation rules.

### 1.2 `sources`: where the raw data comes from

```yaml
sources:
  - id: walking_forest_excel
    type: excel
    path: raw/walking_forest_2025.xlsx
```

- `id`: short label you use later in `tables`.
- `type`: how to read the file (`excel` for xlsx/xls; other types can be added later).
- `path`: path to the raw file, relative to the dataset directory.

You can add multiple sources if your dataset has several raw files.

### 1.3 `tables`: define canonical tables

Each entry in `tables` describes one canonical table the pipeline will create from a sheet or file.

Example (Excel with sheets):

```yaml
tables:

  oak_measurements:
    source: walking_forest_excel
    sheet: "Oak measurements"
    rename:
      "ID": id
      "Species": species_verbatim
      "DBH (cm)": dbh_cm
      "Height (m)": height_m
      "Browsing": browsing_present
```

Key ideas:

- The key `oak_measurements` becomes the table name (`staging/oak_measurements.parquet`, `processed/oak_measurements.parquet`).
- `source`: must match one of the `sources.id` entries.
- `sheet` (for Excel): which sheet to read.
- `rename`: map raw column headers → clean canonical column names.

Guidelines for canonical column names:

- Use `snake_case`: `dbh_cm`, `soil_moisture_pct`, `date_local`.
- Make names semantic, not positional: `height_m` instead of `H1`.
- Keep units in the name when important: `*_cm`, `*_m`, `*_pct`.

You can define multiple tables that all come from the same Excel file but different sheets (as in `oak_measurements`, `control_plots`, `soil_measurements`, etc.).

### 1.4 `derivations`: computed/cleaned columns

`derivations` specify simple column-level calculations that apply to all tables where their source columns exist.

Example (from walking_forest):

```yaml
derivations:
  - target: dbh_m
    source: dbh_cm
    operation: divide
    value: 100
    unit: m
    description: "Convert DBH from cm to meters"

  - target: datetime_local
    sources: [date_local, time_local]
    operation: combine_datetime_flexible
    assume_year: 2024
    dayfirst: true
    description: "Combine date and time into datetime_local"
```

Supported operations (current pipeline):

- `divide`: numeric unit conversion, e.g. cm → m.
- `combine_datetime_flexible`: join `date` + `time` columns into a single timestamp.

Guidelines:

- Use `derivations` for *simple, repeatable* column logic (unit conversions, combining columns).
- Do **not** bake complex ecological logic here; that belongs in analysis or explicit mapping.
- For IDs, prefer to keep raw IDs as-is and handle any “ID hygiene” via mappings/remarks instead of destructive editing.

## 2. DwC mapping: `mappings/dwc_standard.yaml`

This file explains how canonical tables map to Darwin Core (DwC) terms. It is only needed when your profile’s data standard is DwC (`darwin_core` / `dwc`).

Structure (simplified):

```yaml
meta:
  standard: Darwin Core
  version: 2023-10

tables:

  oak_measurements.parquet:

    event:
      eventID: id

    occurrence:
      occurrenceID: id
      scientificName: species_verbatim
      basisOfRecord:
        constant: HumanObservation

    measurements:
      - source: dbh_cm
        measurementType: diameter at breast height
        measurementUnit: cm
```

Concepts:

- Top-level `tables`: one key per canonical table (e.g. `oak_measurements.parquet`).
- Under each table:
  - `event`: how to build rows for `event` (DwC core).
  - `occurrence`: how to build `occurrence` rows (optional for some tables).
  - `measurements`: list of measurements that become rows in `measurement_or_fact`.

### 2.1 `event` mapping

Example:

```yaml
event:
  eventID: id
  eventDate: datetime_local
```

- Keys (left side) are DwC terms: `eventID`, `eventDate`, `samplingProtocol`, etc.
- Values:
  - A canonical column name (string) → value taken from that column.
  - Or a dict with `constant: ...` to fill a fixed value.

Guidelines:

- `eventID` should point to a stable identifier column (often your plot or sample id).
- If a raw ID is messy (e.g. contains timestamps), consider creating a clean canonical ID via `derivations` and mapping `eventID` to that, preserving the original in `eventRemarks`.

### 2.2 `occurrence` mapping

Example:

```yaml
occurrence:
  occurrenceID: id
  scientificName: taxon_verbatim
  individualCount: individual_count
  basisOfRecord:
    constant: HumanObservation
  occurrenceStatus:
    constant: present
```

- `occurrenceID`: stable ID for the occurrence; can reuse `id` when appropriate.
- `scientificName`: mapped from your canonical taxon column.
- Optional fields like `individualCount`, `basisOfRecord`, `occurrenceStatus` can come from columns or constants.

If an occurrence table does not have its own clean ID, the exporter will synthesize an `occurrenceID` and mark it in `occurrenceRemarks`.

### 2.3 `measurements` mapping

Each entry describes one variable that becomes one or more rows in `measurement_or_fact`.

Example:

```yaml
measurements:
  - source: dbh_cm
    measurementType: diameter at breast height
    measurementUnit: cm

  - source: soil_moisture_pct
    measurementType: soil moisture
    measurementUnit: percent
    measurementRemarks: "Field replicate; see methods in EML"
```

- `source`: canonical column name.
- `measurementType`: human-readable name of the variable.
- `measurementUnit`: unit string (used for both human reading and ontology lookup).
- Optional:
  - `measurementRemarks`: free text or note that appears in `measurementRemarks`.

Ontology links for `measurementType` / `measurementUnit` are configured in the `ontology_annotations` section.

### 2.4 `ontology_annotations`

Example excerpt:

```yaml
ontology_annotations:

  measurementType:
    soil moisture:
      ECSO: http://purl.dataone.org/odo/ECSO_00000517

  measurementUnit:
    m:
      UO: http://purl.obolibrary.org/obo/UO_0000008
    percent:
      UO: http://purl.obolibrary.org/obo/UO_0000187
```

- Under `measurementType`, keys match the `measurementType` strings used above.
- Under `measurementUnit`, keys match the `measurementUnit` strings.
- Values are ontology term URIs grouped by vocabulary prefix (ECSO, UO, ENVO, etc.).

The exporter will pick the first URI per term and put it into `measurementTypeID` / `measurementUnitID`.

## 3. ID hygiene guidelines (very important)

To keep identifiers scientifically robust and DwC-friendly:

- Use human-readable, stable IDs where possible (e.g. `MW_Oak_01`).
- An ID is good for `eventID` / `occurrenceID` if it:
  - Refers to one sampling event or occurrence.
  - Does not change between exports.
  - Does not need to be re-parsed to understand meaning.
- If an ID column mixes ID + timestamp or other stuff (e.g. `Control_359,2025-04-17 10:30:00`):
  - Prefer to keep that raw string as provenance (e.g. in `eventRemarks` or a separate canonical column).
  - Optionally define a new clean ID via `derivations` and map DwC `eventID` / `occurrenceID` to the clean column.
- Avoid "fixing" IDs manually in Excel after the config exists; instead, express the change via `dataset.yaml` + mappings so it remains reproducible.

## 4. What authors should NOT worry about

As a dataset author using this pipeline, you do **not** need to:

- Write Python code.
- Understand Pandas or Parquet internals.
- Know all details of Darwin Core or RO-Crate.

Your responsibilities are:

- Provide/organise the raw data files under `raw/`.
- Fill out `dataset.yaml` with sources, tables, renames, and simple derivations.
- Work with someone (or examples) to set up a mapping file like `mappings/dwc_standard.yaml` once per dataset.

The pipeline and profiles take care of:

- Reading the data.
- Creating canonical tables.
- Exporting DwC tables.
- Generating EML/JSON-LD/RO-Crate.
- Running validation and building the publication package.
