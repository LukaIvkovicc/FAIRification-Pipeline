"""Export tabular data products in community standards (currently DwC).

This script is intended as a generic "standard exporter" for datasets.
At the moment it only implements Darwin Core (DwC) as the tabular
standard, but the entrypoint is structured so that additional
exporters (e.g. for hydrology, soil chemistry, sensor time series)
can be plugged in later and selected via dataset profiles.

Inputs (per dataset directory):
- processed/*.parquet        (from transform step)
- mappings/dwc_standard.yaml (mapping + ontology annotations, for DwC)

Outputs for DwC (in canonical/ or exports/standard):
- canonical/event.parquet
- canonical/occurrence.parquet
- canonical/measurement_or_fact.parquet
"""

from pathlib import Path
import argparse
from typing import Dict, Any, List, Callable
import pandas as pd
import yaml
from etl.helpers.config_validation import (
    resolve_dataset_config_path,
    validate_dataset_yaml,
    validate_profile_yaml,
    validate_mapping_yaml,
    report_and_maybe_abort,
)
from etl.helpers.reconcile_mapping import reconcile_tables_cfg_with_processed


# Standard aliases (single source of truth for normalization)
_STANDARD_ALIASES = {"darwin_core": "dwc", "dwc": "dwc"}


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_mapping(mapping_path: Path) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Load DwC mapping and return (tables_cfg, ontology_annotations)."""
    cfg = load_yaml(mapping_path)
    errors, warnings = validate_mapping_yaml(cfg, mapping_path)
    report_and_maybe_abort(errors, warnings, fatal=True)

    tables_cfg = cfg.get("tables", {}) if isinstance(cfg, dict) else {}
    ontology = cfg.get("ontology_annotations", {}) if isinstance(cfg, dict) else {}
    return tables_cfg, ontology


def pick_first_uri(info: Any) -> str | None:
    """Given a dict like {"ENVO": "uri"}, return the first URI value."""
    if isinstance(info, dict):
        for v in info.values():
            return v
    return None


def norm_id(x: Any) -> str | None:
    """Normalize identifier-like values to a clean string or None.

    Treats None, pandas NA/nan, empty/whitespace-only strings and
    common textual representations of missing values as None.
    """
    if x is None or pd.isna(x):
        return None
    s = str(x).strip()
    if not s or s.lower() in {"nan", "<na>", "none", "null"}:
        return None
    return s


def export_dwc(
    processed_dir: Path,
    mapping_path: Path,
    out_dir: Path,
    csv_dir: Path | None = None,
) -> None:
    if not mapping_path.exists():
        raise SystemExit(f"DwC mapping file not found: {mapping_path}")

    ensure_dir(out_dir)

    tables_cfg, ontology = load_mapping(mapping_path)
    if not tables_cfg:
        raise SystemExit(f"DwC mapping has no tables configured: {mapping_path}")

    events_by_id: Dict[str, Dict[str, Any]] = {}
    occurrences: list[Dict[str, Any]] = []
    measurements: list[Dict[str, Any]] = []

    mt_onto = ontology.get("measurementType", {}) if isinstance(ontology, dict) else {}
    mu_onto = ontology.get("measurementUnit", {}) if isinstance(ontology, dict) else {}

    # Strict validation: ensure mapping references exist in processed tables.
    validation_errors: dict = {}
    for table_file, table_map in tables_cfg.items():
        if table_file.endswith(".parquet"):
            table_filename = table_file
        else:
            table_filename = f"{table_file}.parquet"

        src_path = processed_dir / table_filename
        if not src_path.exists():
            alt_path = processed_dir / table_file
            if alt_path.exists():
                src_path = alt_path
            else:
                validation_errors[table_filename] = {"missing_table": True}
                continue

        try:
            df_proc = pd.read_parquet(src_path)
        except Exception:
            validation_errors[table_filename] = {"missing_table": True}
            continue

        cols = set(str(c) for c in df_proc.columns)
        missing_cols: set = set()

        # eventID
        event_spec = table_map.get("event") or {}
        if isinstance(event_spec, dict):
            e_id = event_spec.get("eventID")
            if isinstance(e_id, str) and e_id not in cols:
                missing_cols.add(e_id)

        # occurrence fields (scientificName required when present)
        occ_spec = table_map.get("occurrence") or {}
        if isinstance(occ_spec, dict):
            sci = occ_spec.get("scientificName")
            if isinstance(sci, str) and sci not in cols:
                missing_cols.add(sci)
            for k, v in occ_spec.items():
                if k == "prefix":
                    continue
                if isinstance(v, str) and v not in cols:
                    missing_cols.add(v)

        # measurements
        for m in table_map.get("measurements", []) or []:
            if not isinstance(m, dict):
                continue
            src_col = m.get("source")
            if isinstance(src_col, str) and src_col not in cols:
                missing_cols.add(src_col)

        if missing_cols:
            validation_errors[table_filename] = sorted(list(missing_cols))

    if validation_errors:
        print("[DwC] Validation failed: mapping references missing processed columns.")
        for t, miss in validation_errors.items():
            if isinstance(miss, dict) and miss.get("missing_table"):
                print(f"  {t}: processed table not found in {processed_dir}")
            else:
                print(f"  {t}: missing columns: {miss}")
        raise SystemExit(
            "Aborting export. Fix mapping or run transform/ingest; or run with --auto-reconcile to attempt automatic alignment."
        )

    # Iterate mappings per table
    for table_file, table_map in tables_cfg.items():
        # Allow mapping keys with or without the .parquet extension
        if table_file.endswith(".parquet"):
            table_filename = table_file
        else:
            table_filename = f"{table_file}.parquet"

        src_path = processed_dir / table_filename
        if not src_path.exists():
            # Fallback: try the raw key as provided (covers subdirs or explicit filenames)
            alt_path = processed_dir / table_file
            if alt_path.exists():
                src_path = alt_path
            else:
                print(
                    f"[DwC] Warning: source table not found, skipping. Tried: {processed_dir / table_filename} and {processed_dir / table_file}"
                )
                continue

        df = pd.read_parquet(src_path)
        # Check for measurement source columns referenced in mapping but missing
        missing_measurement_sources: set = set()
        for m in table_map.get("measurements", []) or []:
            if not isinstance(m, dict):
                continue
            src_col = m.get("source")
            if src_col and src_col not in df.columns:
                missing_measurement_sources.add(src_col)
        if missing_measurement_sources:
            print(
                f"[DwC] Warning: table {table_filename} mapping references missing measurement source columns: {sorted(list(missing_measurement_sources))}"
            )

        # ----- events -----
        event_spec = table_map.get("event") or {}
        event_id_spec = event_spec.get("eventID")
        # Determine whether eventID is provided as a column name or a constant
        event_id_col = None
        event_id_const = None
        if isinstance(event_id_spec, str) and event_id_spec in df.columns:
            event_id_col = event_id_spec
        elif isinstance(event_id_spec, dict) and "constant" in event_id_spec:
            val = event_id_spec.get("constant")
            event_id_const = norm_id(val)

        # If mapping provides a constant eventID, materialize a minimal event
        if event_id_const is not None:
            ev: Dict[str, Any] = {"eventID": event_id_const}
            for dwc_name, spec in event_spec.items():
                if dwc_name == "eventID":
                    continue
                if isinstance(spec, dict) and "constant" in spec:
                    ev[dwc_name] = spec.get("constant")
            # Prefer merging later, but ensure at least a minimal event exists
            existing = events_by_id.get(event_id_const, {})
            for k, v in ev.items():
                if k not in existing or existing[k] in (None, ""):
                    existing[k] = v
            events_by_id[event_id_const] = existing

        if event_id_col:
            subset = df.loc[df[event_id_col].notna()].copy()
            subset = subset.drop_duplicates(subset=[event_id_col])
            for _, row in subset.iterrows():
                raw_e = row[event_id_col]
                nid = norm_id(raw_e)
                if nid is None:
                    # skip rows with unusable/empty event id after normalization
                    continue
                eid = nid

                # Start each event record with its ID
                ev: Dict[str, Any] = {"eventID": eid}

                # Map additional DwC event fields, supporting both column mappings
                # and simple constants defined in the mapping YAML.
                for dwc_name, spec in event_spec.items():
                    if dwc_name == "eventID":
                        continue
                    if isinstance(spec, str) and spec in row.index:
                        value = row[spec]
                        if pd.notna(value):
                            ev[dwc_name] = value
                    elif isinstance(spec, dict) and "constant" in spec:
                        ev[dwc_name] = spec.get("constant")

                existing = events_by_id.get(eid, {})
                # Merge, preferring any non-empty values we just derived.
                for k, v in ev.items():
                    if k not in existing or existing[k] in (None, ""):
                        existing[k] = v
                events_by_id[eid] = existing

        # ----- occurrences and measurements -----
        occ_map = table_map.get("occurrence") or {}
        has_occ = isinstance(occ_map, dict) and "scientificName" in occ_map

        if has_occ:
            prefix = occ_map.get("prefix", "occ")
            sci_col = occ_map["scientificName"]
            occid_colname = occ_map.get("occurrenceID")

            # Ensure the scientificName column referenced by the mapping exists;
            # if it doesn't, fail fast with a clear error to avoid silent data loss.
            if sci_col not in df.columns:
                raise SystemExit(
                    f"[DwC] '{table_file}': occurrence.scientificName column '{sci_col}' not found in {src_path.name}"
                )

            # Use .loc + .copy() to ensure we always have a concrete DataFrame
            # object (helps linters and avoids view-related surprises).
            df_occ = df.loc[df[sci_col].notna()].copy()
            # Tell static type checkers (Pylance/mypy) that df_occ is indeed a DataFrame
            assert isinstance(df_occ, pd.DataFrame)

            # Drop rows that do not have a valid event identifier only when
            # there is no constant fallback available. If the mapping provides
            # a constant eventID, missing column values can fall back to it.
            if (
                event_id_col is not None
                and event_id_col in df_occ.columns
                and event_id_const is None
            ):
                df_occ = df_occ.loc[df_occ[event_id_col].notna()]

            for j, (_, row) in enumerate(df_occ.iterrows()):
                # Determine event id for this row: prefer column, then constant, else synthesize
                if event_id_col and event_id_col in row.index:
                    nid = norm_id(row.get(event_id_col))
                    if nid is not None:
                        eid = nid
                    elif event_id_const is not None:
                        eid = event_id_const
                    else:
                        eid = None
                elif event_id_const is not None:
                    eid = event_id_const
                else:
                    eid = f"event_{table_filename}_{j}"
                    # Ensure minimal event record exists to avoid orphans
                    events_by_id.setdefault(eid, {"eventID": eid})

                # If we couldn't obtain an event ID by column or constant,
                # we must skip building an occurrence here — canonical DwC
                # occurrence rows must reference a valid eventID.
                if eid is None:
                    continue
                if occid_colname and occid_colname in row.index and pd.notna(row.get(occid_colname)):
                    occid_n = norm_id(row.get(occid_colname))
                    if occid_n is not None:
                        occid = occid_n
                        synthesized = False
                    else:
                        # If normalization makes the provided occurrenceID unusable,
                        # synthesize a stable one instead of emitting None.
                        base_id = eid or "event"
                        occid = f"{base_id}_{prefix}_{j}"
                        synthesized = True
                else:
                    base_id = eid or "event"
                    occid = f"{base_id}_{prefix}_{j}"
                    synthesized = True

                occ: Dict[str, Any] = {
                    "occurrenceID": occid,
                    "eventID": eid,
                    "scientificName": row.get(sci_col),
                }
                if "individualCount" in occ_map and occ_map["individualCount"] in row.index:
                    occ["individualCount"] = row.get(occ_map["individualCount"])
                if synthesized:
                    occ["occurrenceRemarks"] = f"synthesized by export_standard.py; source={table_file}"

                # Map any additional DwC occurrence fields, allowing constants.
                for dwc_name, spec in occ_map.items():
                    if dwc_name in {"occurrenceID", "scientificName", "individualCount", "prefix"}:
                        continue
                    if isinstance(spec, str) and spec in row.index:
                        value = row.get(spec)
                        if pd.notna(value):
                            occ[dwc_name] = value
                    elif isinstance(spec, dict) and "constant" in spec:
                        occ[dwc_name] = spec.get("constant")

                occurrences.append(occ)

                for m in table_map.get("measurements", []) or []:
                    if not isinstance(m, dict):
                        continue
                    src_col = m.get("source")
                    if not src_col or src_col not in row.index or pd.isna(row[src_col]):
                        continue

                    mt = m.get("measurementType") or src_col
                    mu = m.get("measurementUnit", "")

                    mt_id = pick_first_uri(mt_onto.get(mt))
                    mu_id = pick_first_uri(mu_onto.get(mu))

                    # Skip any measurement rows that would reference a missing eventID
                    if eid is None:
                        continue

                    meas: Dict[str, Any] = {
                        "measurementID": f"m_{occid}_{src_col}",
                        "occurrenceID": occid,
                        "eventID": eid,
                        "measurementType": mt,
                        "measurementValue": row[src_col],
                        "measurementUnit": mu,
                    }
                    if mt_id:
                        meas["measurementTypeID"] = mt_id
                    if mu_id:
                        meas["measurementUnitID"] = mu_id

                    # Optional remarks: combine mapping-level and row-level notes if present.
                    remarks: list[str] = []
                    mapping_remark = m.get("measurementRemarks")
                    if isinstance(mapping_remark, str) and mapping_remark.strip():
                        remarks.append(mapping_remark.strip())

                    notes_col = f"{src_col}_notes"
                    if notes_col in row.index and pd.notna(row[notes_col]):
                        remarks.append(str(row[notes_col]))

                    if remarks:
                        meas["measurementRemarks"] = " | ".join(remarks)

                    measurements.append(meas)

        else:
            for j, (_, row) in enumerate(df.iterrows()):
                # Skip rows without a usable event identifier so that we
                # do not create orphan measurements referencing null/NaN
                # eventIDs in the canonical output.
                if event_id_col and event_id_col in row.index and pd.isna(row[event_id_col]):
                    # attempt to normalize; if unusable and no constant, skip
                    nid = norm_id(row.get(event_id_col))
                    if nid is None and event_id_const is None:
                        continue

                if event_id_col and event_id_col in row.index:
                    nid = norm_id(row.get(event_id_col))
                    if nid is not None:
                        eid = nid
                    elif event_id_const is not None:
                        eid = event_id_const
                    else:
                        eid = None
                elif event_id_const is not None:
                    eid = event_id_const
                else:
                    eid = f"event_{table_filename}_{j}"
                    events_by_id.setdefault(eid, {"eventID": eid})

                for m in table_map.get("measurements", []) or []:
                    if not isinstance(m, dict):
                        continue
                    src_col = m.get("source")
                    if not src_col or src_col not in row.index or pd.isna(row[src_col]):
                        continue

                    mt = m.get("measurementType") or src_col
                    mu = m.get("measurementUnit", "")

                    mt_id = pick_first_uri(mt_onto.get(mt))
                    mu_id = pick_first_uri(mu_onto.get(mu))

                    # Skip measurements that would reference a missing eventID
                    if eid is None:
                        continue

                    meas: Dict[str, Any] = {
                        "measurementID": f"m_{eid}_{src_col}",
                        "eventID": eid,
                        "measurementType": mt,
                        "measurementValue": row[src_col],
                        "measurementUnit": mu,
                    }
                    if mt_id:
                        meas["measurementTypeID"] = mt_id
                    if mu_id:
                        meas["measurementUnitID"] = mu_id

                    # Optional remarks: combine mapping-level and row-level notes if present.
                    remarks: list[str] = []
                    mapping_remark = m.get("measurementRemarks")
                    if isinstance(mapping_remark, str) and mapping_remark.strip():
                        remarks.append(mapping_remark.strip())

                    notes_col = f"{src_col}_notes"
                    if notes_col in row.index and pd.notna(row[notes_col]):
                        remarks.append(str(row[notes_col]))

                    if remarks:
                        meas["measurementRemarks"] = " | ".join(remarks)

                    # Skip measurements that would reference a missing eventID
                    if eid is None:
                        continue

                    measurements.append(meas)

    # Write canonical DwC-style Parquet tables
    df_event: pd.DataFrame | None = None
    df_occ: pd.DataFrame | None = None
    df_meas: pd.DataFrame | None = None

    if events_by_id:
        df_event = pd.DataFrame(list(events_by_id.values())).drop_duplicates(subset=["eventID"])
        if "eventID" in df_event.columns:
            df_event["eventID"] = df_event["eventID"].astype("string")
        df_event.to_parquet(out_dir / "event.parquet", index=False)
    if occurrences:
        df_occ = pd.DataFrame(occurrences).drop_duplicates(subset=["occurrenceID"])
        if "occurrenceID" in df_occ.columns:
            df_occ["occurrenceID"] = df_occ["occurrenceID"].astype("string")
        if "eventID" in df_occ.columns:
            df_occ["eventID"] = df_occ["eventID"].astype("string")
        df_occ.to_parquet(out_dir / "occurrence.parquet", index=False)
    if measurements:
        mf = pd.DataFrame(measurements)

        # Ensure measurement IDs are unique across the table. If any
        # duplicates are detected (for example when multiple source
        # tables or mappings accidentally generate the same logical ID),
        # fall back to a simple sequential identifier that is guaranteed
        # to be unique within this dataset export.
        if "measurementID" in mf.columns and mf["measurementID"].duplicated().any():
            # Ensure IDs are strings before grouping to avoid mixed-type surprises
            mf["measurementID"] = mf["measurementID"].astype("string")
            # Suffix duplicate IDs rather than replace them, preserving provenance
            dup_counts = mf.groupby("measurementID").cumcount()
            mask = dup_counts > 0
            mf.loc[mask, "measurementID"] = mf.loc[mask, "measurementID"] + "__dup" + dup_counts.loc[mask].astype(str)

        # Ensure measurementValue is always stored as string so mixed
        # numeric/text values (e.g. "open", "a", 0.3) do not trigger
        # Arrow type inference errors.
        if "measurementValue" in mf.columns:
            mf["measurementValue"] = mf["measurementValue"].astype(str)

        # Cast identifiers to pandas string dtype while preserving
        # missing values as proper NA rather than the literal strings
        # "nan" or "<NA>", which can otherwise confuse downstream
        # validation when checking referential integrity.
        for id_col in ["measurementID", "occurrenceID", "eventID"]:
            if id_col in mf.columns:
                mf[id_col] = mf[id_col].astype("string")

        mf.to_parquet(out_dir / "measurement_or_fact.parquet", index=False)
        df_meas = mf

    # Referential integrity checks (warn if canonical links are broken)
    try:
        event_ids = set()
        occ_ids = set()
        if df_event is not None and 'eventID' in df_event.columns:
            event_ids = set(df_event['eventID'].dropna().astype(str).tolist())
        if df_occ is not None and 'occurrenceID' in df_occ.columns:
            occ_ids = set(df_occ['occurrenceID'].dropna().astype(str).tolist())

        if df_occ is not None and 'eventID' in df_occ.columns:
            missing = set(df_occ['eventID'].dropna().astype(str).tolist()) - event_ids
            if missing:
                sample = list(missing)[:5]
                print(f"[DwC] Warning: {len(missing)} occurrence.eventID values have no matching eventID; examples: {sample}")

        if df_meas is not None:
            if 'eventID' in df_meas.columns:
                missing = set(df_meas['eventID'].dropna().astype(str).tolist()) - event_ids
                if missing:
                    sample = list(missing)[:5]
                    print(f"[DwC] Warning: {len(missing)} measurement.eventID values have no matching eventID; examples: {sample}")
            if 'occurrenceID' in df_meas.columns and occ_ids:
                missing = set(df_meas['occurrenceID'].dropna().astype(str).tolist()) - occ_ids
                if missing:
                    sample = list(missing)[:5]
                    print(f"[DwC] Warning: {len(missing)} measurement.occurrenceID values have no matching occurrenceID; examples: {sample}")
    except Exception:
        # Non-fatal: do not interrupt export on diagnostic failure
        pass

    # Optional CSV export for repositories that prefer CSV uploads
    if csv_dir is not None:
        ensure_dir(csv_dir)
        if df_event is not None:
            df_event.to_csv(csv_dir / "event.csv", index=False)
        if df_occ is not None:
            df_occ.to_csv(csv_dir / "occurrence.csv", index=False)
        if df_meas is not None:
            df_meas.to_csv(csv_dir / "measurement_or_fact.csv", index=False)
    if not any([events_by_id, occurrences, measurements]):
        print("[DwC] Warning: no DwC rows generated; check mapping and processed data.")
    else:
        print(f"Standard-compliant DwC tables written to {out_dir}")


def export_standard(
    processed_dir: Path,
    mapping_path: Path,
    out_dir: Path,
    csv_dir: Path | None = None,
    standard: str = "dwc",
) -> None:
    """Dispatcher for tabular standard exporters.

    Parameters
    ----------
    processed_dir : Path
        Directory with processed Parquet tables.
    mapping_path : Path
        Path to mapping configuration (DwC mapping for now).
    out_dir : Path
        Directory where canonical/standardised tables will be written.
    csv_dir : Path | None
        Optional directory for CSV copies.
    standard : str
        Logical name of the standard ("dwc" for Darwin Core). More
        options can be added later via the _EXPORTERS registry.
    """

    exporters: Dict[str, Callable[..., None]] = {
        "dwc": export_dwc,
        # future: "om": export_om, "timeseries": export_timeseries, ...
    }

    # Normalize standard using module-level aliases
    key = _STANDARD_ALIASES.get(standard, standard)
    exporter = exporters.get(key)
    if exporter is None:
        raise SystemExit(f"Unknown tabular standard: {standard}")

    print(
        f"Exporting tabular standard '{key}' (requested='{standard}') "
        f"from mapping {mapping_path} to {out_dir}"
    )

    exporter(
        processed_dir=processed_dir,
        mapping_path=mapping_path,
        out_dir=out_dir,
        csv_dir=csv_dir,
    )


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Export processed tables to a selected community standard (currently DwC)."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        required=True,
        help="Path to the dataset directory (contains processed/, mappings/, dataset.yaml)",
    )
    parser.add_argument(
        "--standard",
        default=None,
        help="Logical name of tabular standard (e.g. dwc). Defaults to profile defaults.standards.data or 'dwc'.",
    )
    parser.add_argument("--processed", type=Path, default=None, help="Processed directory (Parquet); defaults to <dataset_dir>/processed")
    parser.add_argument(
        "--mapping",
        type=Path,
        default=None,
        help="Mapping YAML path (DwC mapping for 'dwc' standard); defaults to <dataset_dir>/mappings/dwc_standard.yaml",
    )
    parser.add_argument("--out", type=Path, default=None, help="Output directory for canonical tables; defaults to <dataset_dir>/canonical")
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory to also write CSV versions of the canonical DwC tables. "
            "Defaults to <dataset_dir>/exports/dwc when dataset.outputs.dwc_csv is true."
        ),
    )
    parser.add_argument(
        "--auto-reconcile",
        action="store_true",
        help=(
            "If mapping references missing source columns, attempt to align them to "
            "processed column names using mappings/clean_columns.yaml and fuzzy matching."
        ),
    )
    parser.add_argument(
        "--write-reconciled",
        type=Path,
        default=None,
        help="Optional path to write the reconciled mapping YAML for inspection.",
    )
    args = parser.parse_args(argv)

    dataset_dir = args.dataset_dir.resolve()

    # Inspect dataset/profile to choose sensible defaults for standard and CSV dir.
    dataset_yaml_path = resolve_dataset_config_path(dataset_dir, explicit=None)
    dataset_cfg = load_yaml(dataset_yaml_path)
    ds_errors, ds_warnings = validate_dataset_yaml(dataset_cfg, dataset_yaml_path)
    report_and_maybe_abort(ds_errors, ds_warnings, fatal=True)
    d = dataset_cfg.get("dataset", {}) if isinstance(dataset_cfg, dict) else {}
    profile_id = d.get("profile")
    outputs_cfg_dataset = dataset_cfg.get("outputs", {}) if isinstance(dataset_cfg, dict) else {}

    default_standard = "dwc"  # safe fallback
    profile_cfg: Dict[str, Any] = {}
    if profile_id:
        profiles_dir = dataset_dir.parent / "profiles"
        profile_path = profiles_dir / f"{profile_id}.yaml"
        profile_cfg = load_yaml(profile_path)
        pr_errors, pr_warnings = validate_profile_yaml(profile_cfg, profile_path)
        report_and_maybe_abort(pr_errors, pr_warnings, fatal=False)
        stds = (profile_cfg.get("defaults") or {}).get("standards") or {}
        data_std = stds.get("data") if isinstance(stds, dict) else None
        if isinstance(data_std, str) and data_std:
            default_standard = data_std

    standard = args.standard or default_standard

    # Normalize logical standard to mapping key and pick mapping file accordingly
    key = _STANDARD_ALIASES.get(standard, standard)

    processed_dir = args.processed or (dataset_dir / "processed")
    mapping_path = args.mapping or (dataset_dir / "mappings" / f"{key}_standard.yaml")
    out_dir = args.out or (dataset_dir / "canonical")
    auto_reconcile = bool(args.auto_reconcile)
    write_reconciled = args.write_reconciled

    # Friendly early check: if the approved mapping file is missing, provide
    # a clear, actionable message that tells the user how to generate a
    # suggested mapping and promote it to an approved mapping.
    if not mapping_path.exists():
        print(f"[DwC] No approved mapping found at {mapping_path}")
        print("  → Generate a suggested mapping (one-time bootstrap):")
        print("      make pipeline-draft DATASET=<your-dataset-path>")
        print(
            f"  → Or (manual): PYTHONPATH=. python -m etl.helpers.suggest_mapping --dataset-dir {dataset_dir} --emit-standard"
        )
        print("  → Review the suggested file and promote it to an approved mapping:")
        print(
            f"      cp {dataset_dir}/mappings/{key}_suggested.yaml {dataset_dir}/mappings/{key}_standard.yaml"
        )
        print("  → Or use validated promotion (approver helper):")
        print(
            f"      PYTHONPATH=. python -m etl.helpers.approve_mapping --dataset-dir {dataset_dir} --suggested {dataset_dir}/mappings/{key}_suggested.yaml"
        )
        raise SystemExit("Aborting: no approved mapping found; see instructions above.")

    # Optionally reconcile mapping source names against processed columns
    if auto_reconcile:
        cfg = load_yaml(mapping_path)
        tables_cfg = cfg.get("tables", {}) if isinstance(cfg, dict) else {}
        clean_path = dataset_dir / "mappings" / "clean_columns.yaml"
        new_tables_cfg, reconcile_report = reconcile_tables_cfg_with_processed(
            tables_cfg, processed_dir, clean_columns_path=clean_path, threshold=0.75
        )

        # write reconciled mapping to user-specified path or a sensible default
        reconciled_path = write_reconciled or (dataset_dir / "mappings" / f"{key}_standard_reconciled.yaml")
        out_payload = dict(cfg) if isinstance(cfg, dict) else {}
        out_payload["tables"] = new_tables_cfg
        # ensure meta indicates the mapping uses canonical column names
        meta = out_payload.get("meta") if isinstance(out_payload.get("meta"), dict) else {}
        meta["column_schema"] = "canonical"
        out_payload["meta"] = meta
        ensure_dir(reconciled_path.parent)
        with open(reconciled_path, "w", encoding="utf-8") as wf:
            yaml.safe_dump(out_payload, wf, sort_keys=False, allow_unicode=True)
        print(f"Wrote reconciled mapping to {reconciled_path}")

        if reconcile_report.get("replacements"):
            print("[reconcile] Applied replacements:")
            for t, reps in reconcile_report["replacements"].items():
                for r in reps:
                    print(f"  {t}: {r['from']} -> {r['to']}")
        if reconcile_report.get("unresolved"):
            print("[reconcile] Unresolved source names (need manual fix):")
            for t, items in reconcile_report["unresolved"].items():
                print(f"  {t}: {items}")

        # point exporter to the reconciled mapping file
        mapping_path = reconciled_path

    # Decide whether to write DwC CSV copies, with precedence:
    # 1) dataset.yaml.outputs.dwc_csv (if set)
    # 2) profile.outputs.dwc_csv (if set)
    # 3) otherwise: no CSV exports unless --csv-dir is explicitly given.
    outputs_cfg_profile = profile_cfg.get("outputs", {}) if isinstance(profile_cfg, dict) else {}
    dwc_csv_flag = None
    if isinstance(outputs_cfg_dataset, dict) and "dwc_csv" in outputs_cfg_dataset:
        dwc_csv_flag = bool(outputs_cfg_dataset.get("dwc_csv"))
    elif isinstance(outputs_cfg_profile, dict) and "dwc_csv" in outputs_cfg_profile:
        dwc_csv_flag = bool(outputs_cfg_profile.get("dwc_csv"))

    csv_dir = args.csv_dir
    if csv_dir is None and dwc_csv_flag:
        csv_dir = dataset_dir / "exports" / "dwc"

    export_standard(
        processed_dir=processed_dir,
        mapping_path=mapping_path,
        out_dir=out_dir,
        csv_dir=csv_dir,
        standard=standard,
    )


if __name__ == "__main__":
    main()
