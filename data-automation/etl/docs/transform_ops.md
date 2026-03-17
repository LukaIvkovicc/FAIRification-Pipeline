Transform operations
====================

This document lists the minimal, safe transform operations supported by the ETL `apply_derivations()` engine (implemented in `etl/transform.py`).

Location
- Dataset derivations go in `dataset.yaml` under the top-level `derivations:` list. The `transform` step applies these rules to each staging table and writes results to `<dataset_dir>/processed/`.

Principles
- All ops are single-table and guarded: missing source columns are skipped for safety.
- Ops are domain-neutral and deterministic.
- Keep transforms minimal — heavy validation, cross-table joins, and aggregations belong in later steps or custom profiles.

Supported operations

1) divide
- Description: divide a numeric source column by a constant denominator.
- Example:

```yaml
- operation: divide
  source: dbh_cm
  target: dbh_m
  value: 100
```

2) combine_datetime_flexible
- Description: combine a date column and a time column into a single datetime. Handles missing-year injection and `dayfirst` parsing.
- Example:

```yaml
- operation: combine_datetime_flexible
  sources: [date_col, time_col]
  target: eventDate
  dayfirst: true
  assume_year: 2022
```

3) copy
- Description: duplicate a column under a new name.
- Example:

```yaml
- operation: copy
  source: PlotID
  target: plot_id
```

4) to_numeric
- Description: coerce a column to numeric, invalid values -> NA.
- Example:

```yaml
- operation: to_numeric
  source: Diameter_cm
  target: diameter_cm
```

5) strip
- Description: strip whitespace from string-like columns (preserves NA).
- Example:

```yaml
- operation: strip
  source: species
  target: species
```

6) concat
- Description: concatenate multiple source columns into one, skipping empty parts.
- Example:

```yaml
- operation: concat
  sources: [site, plot, tree]
  target: local_id
  sep: "_"
```

Usage

- Add rules to `dataset.yaml` under `derivations:`. Order matters — rules are applied in list order and can depend on earlier derivations.
- Run transform (from project root):

```bash
cd data-automation
python3 -m etl.transform --dataset-dir datasets/<your_dataset>
```

Notes
- These ops are intentionally minimal to remain predictable and safe. If you need joins, aggregations, or richer unit-handling, implement them in a later step or as profile-specific extensions.
- See `etl/transform.py` and the `apply_derivations()` implementation for exact behavior and edge-case handling.
Transform operations
====================

This document lists the minimal, safe transform operations supported by the ETL `apply_derivations()` engine (implemented in `etl/transform.py`).

Location
- Dataset derivations go in `dataset.yaml` under the top-level `derivations:` list. The `transform` step applies these rules to each staging table and writes results to `<dataset_dir>/processed/`.

Principles
- All ops are single-table and guarded: missing source columns are skipped for safety.
- Ops are domain-neutral and deterministic.
- Keep transforms minimal — heavy validation, cross-table joins, and aggregations belong in later steps or custom profiles.

Supported operations

1) divide
- Description: divide a numeric source column by a constant denominator.
- Example:

```yaml
- operation: divide
  source: dbh_cm
  target: dbh_m
  value: 100
```

2) combine_datetime_flexible
- Description: combine a date column and a time column into a single datetime. Handles missing-year injection and `dayfirst` parsing.
- Example:

```yaml
- operation: combine_datetime_flexible
  sources: [date_col, time_col]
  target: eventDate
  dayfirst: true
  assume_year: 2024
```

3) copy
- Description: duplicate a column under a new name.
- Example:

```yaml
- operation: copy
  source: PlotID
  target: plot_id
```

4) to_numeric
- Description: coerce a column to numeric, invalid values -> NA.
- Example:

```yaml
- operation: to_numeric
  source: Diameter_cm
  target: diameter_cm
```

5) strip
- Description: strip whitespace from string-like columns (preserves NA).
- Example:

```yaml
- operation: strip
  source: species
  target: species
```

6) concat
- Description: concatenate multiple source columns into one, skipping empty parts.
- Example:

```yaml
- operation: concat
  sources: [site, plot, tree]
  target: local_id
  sep: "_"
```

Usage

- Add rules to `dataset.yaml` under `derivations:`. Order matters — rules are applied in list order and can depend on earlier derivations.
- Run transform (from project root):

```bash
cd data-automation
python3 -m etl.transform --dataset-dir datasets/<your_dataset>
```

Notes
- These ops are intentionally minimal to remain predictable and safe. If you need joins, aggregations, or richer unit-handling, implement them in a later step or as profile-specific extensions.
- See `etl/transform.py` and the `apply_derivations()` implementation for exact behavior and edge-case handling.
