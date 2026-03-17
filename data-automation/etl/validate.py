"""Shared ETL validation utilities and dataset-level validation engine.

This module serves two roles:

- Provide reusable Pandera helpers and example domain schemas.
- Offer a generic ``run_validation_for_dataset`` entrypoint that any
    dataset-level ``etl/validate.py`` wrapper can call to produce a
    FAIR-friendly QA report.

The engine is profile-driven where possible and designed to be
extendable to different ecological domains and standards.
"""
from __future__ import annotations
import pandera as pa
from pathlib import Path
from typing import Any, Dict
import argparse
import json
import xml.etree.ElementTree as ET
import pandas as pd
try:
    import pandera.errors as pa_errors
except Exception:  # pragma: no cover - fallback for environments/static checkers
    try:
        from pandera import errors as pa_errors
    except Exception:
        import importlib
        pa_errors = importlib.import_module("pandera.errors")
import yaml

from etl.helpers.config_validation import (
    resolve_dataset_config_path,
    validate_dataset_yaml,
    validate_profile_yaml,
    report_and_maybe_abort,
)


def make_schema_from_config(dtypes: dict, ranges: dict) -> pa.DataFrameSchema:
    """
    Build a simple Pandera schema from config:
    - enforce column presence & dtypes
    - apply min/max numeric ranges where provided
    """
    type_map = {
        "int": pa.Int64,
        "float": pa.Float64,
        "str": pa.String,
        int: pa.Int64,
        float: pa.Float64,
        str: pa.String,
    }

    cols = {}
    for col, typ in dtypes.items():
        T = type_map.get(typ, pa.String)
        checks = []
        if col in ranges:
            lo, hi = ranges[col]
            checks.extend([pa.Check.ge(lo), pa.Check.le(hi)])
        cols[col] = pa.Column(T, nullable=False, checks=checks)
    return pa.DataFrameSchema(columns=cols, coerce=True)


# ---- Optional examples we can specialize later ----

def biodiversity_minimal_schema() -> pa.DataFrameSchema:
    """
    Minimal Darwin Core-like schema for occurrences.
    Extend with more DwC terms when more data arrives.
    """
    return pa.DataFrameSchema({
        "scientificname": pa.Column(pa.String, nullable=False),
        "eventdate": pa.Column(pa.String, nullable=False),  # parse later to datetime
        "decimallatitude": pa.Column(pa.Float64, nullable=False, checks=[pa.Check.ge(-90), pa.Check.le(90)]),
        "decimallongitude": pa.Column(pa.Float64, nullable=False, checks=[pa.Check.ge(-180), pa.Check.le(180)]),
        # add more DwC fields as needed (basisofrecord, occurrenceid, etc.)
    }, coerce=True)


def climate_minimal_schema() -> pa.DataFrameSchema:
    """
    Minimal climate schema (year/site + a couple of variables).
    """
    return pa.DataFrameSchema({
        "year": pa.Column(pa.Int64, nullable=False),
        "site": pa.Column(pa.String, nullable=False),
        "temperature_c": pa.Column(pa.Float64, checks=[pa.Check.ge(-40), pa.Check.le(60)], nullable=True),
        "precipitation_mm": pa.Column(pa.Float64, checks=[pa.Check.ge(0)], nullable=True),
    }, coerce=True)


def validate_df(df: pd.DataFrame, schema: pa.DataFrameSchema) -> tuple[bool, str]:
    """
    Validate 'df' with Pandera. Returns (is_valid, failure_csv_string).
    We return a CSV string of failure cases to write into a report file.
    """
    try:
        schema.validate(df, lazy=True)
        return True, ""
    except pa_errors.SchemaErrors as e:
        return False, e.failure_cases.to_csv(index=False)


# ---------------------------------------------------------------------------
# Dataset-level validation engine
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_profile(dataset_dir: Path, profile_id: str | None) -> Dict[str, Any]:
    if not profile_id:
        return {}
    profiles_dir = dataset_dir.parent / "profiles"
    return _load_yaml(profiles_dir / f"{profile_id}.yaml")


def _check_canonical(dataset_dir: Path, profile: Dict[str, Any]) -> dict:
    """Validate canonical Parquet tables.

    Behaviour is profile-aware:
    - For DwC-like profiles (defaults.standards.data == darwin_core/dwc),
    we expect event/occurrence/measurement_or_fact and run light DwC
    checks (key columns present, basic completeness stats).
    -For other profiles, we simply summarise any ``canonical/*.parquet``
    that exist without imposing DwC-specific expectations.
    """

    canonical_dir = dataset_dir / "canonical"
    report: dict[str, Any] = {"canonical": {}, "errors": []}
    warnings: list[str] = []

    stds = (profile.get("defaults") or {}).get("standards") or {}
    data_std = stds.get("data") if isinstance(stds, dict) else None
    data_std_norm = (str(data_std).strip().lower() if data_std else None)

    # DwC-aware branch
    if data_std_norm in {"darwin_core", "dwc"}:
        eventp = canonical_dir / "event.parquet"
        occp = canonical_dir / "occurrence.parquet"
        measp = canonical_dir / "measurement_or_fact.parquet"

        df_event: pd.DataFrame | None = None
        df_occ: pd.DataFrame | None = None
        df_meas: pd.DataFrame | None = None

        # Structured view of DwC-related checks for dashboards and
        # humans. This is intentionally light-weight: it records
        # whether core tables and recommended terms are present and
        # surfaces a couple of gentle vocabulary hints, without
        # turning everything into hard errors.
        dwc_checks: dict[str, Any] = {}

        required_event_terms = {"eventID", "eventDate"}
        required_occ_terms = {"occurrenceID", "eventID", "scientificName"}
        required_meas_terms = {"measurementID", "measurementType", "measurementValue"}

        # event table
        if not eventp.exists():
            report["errors"].append("missing event.parquet")
        else:  # pragma: no cover - IO
            df_event = pd.read_parquet(eventp)
            cols = list(df_event.columns)
            report["canonical"]["event.parquet"] = {
                "rows": int(len(df_event)),
                "columns": cols,
            }
            dwc_checks["event"] = {
                "has_table": True,
                "required_terms_present": bool(required_event_terms.issubset(set(cols))),
            }

        # occurrence table
        if not occp.exists():
            report["errors"].append("missing occurrence.parquet")
        else:  # pragma: no cover - IO
            df_occ = pd.read_parquet(occp)
            occ_cols = list(df_occ.columns)
            entry: dict[str, Any] = {
                "rows": int(len(df_occ)),
                "columns": occ_cols,
            }
            if "scientificName" in df_occ.columns:
                entry["scientificName_missing_pct"] = float(
                    df_occ["scientificName"].isna().mean()
                )
            report["canonical"]["occurrence.parquet"] = entry

            dwc_checks["occurrence"] = {
                "has_table": True,
                "required_terms_present": bool(required_occ_terms.issubset(set(occ_cols))),
            }

            # track synthesised IDs if exporter flagged them in remarks
            if "occurrenceRemarks" in df_occ.columns:
                synth = df_occ["occurrenceRemarks"].astype(str).str.contains(
                    "synthesized", case=False, na=False
                ).sum()
            else:
                synth = 0
            report["synthesized_occurrence_count"] = int(synth)

        # measurement_or_fact table
        if not measp.exists():
            report["errors"].append("missing measurement_or_fact.parquet")
        else:  # pragma: no cover - IO
            df_meas = pd.read_parquet(measp)
            meas_cols = list(df_meas.columns)
            entry = {
                "rows": int(len(df_meas)),
                "columns": meas_cols,
            }
            missing_cols = [
                col
                for col in ["measurementType", "measurementValue"]
                if col not in df_meas.columns
            ]
            if missing_cols:
                report["errors"].append(
                    "measurement_or_fact.parquet missing columns: "
                    + ", ".join(missing_cols)
                )
            report["canonical"]["measurement_or_fact.parquet"] = entry

            dwc_checks["measurement_or_fact"] = {
                "has_table": True,
                "required_terms_present": bool(required_meas_terms.issubset(set(meas_cols))),
            }

        # Lightweight DwC integrity checks when we have the tables.
        if df_event is not None and df_occ is not None:
            # eventID should be present, non-null and (ideally) unique
            if "eventID" not in df_event.columns:
                report["errors"].append("event.parquet missing eventID column")
            else:
                eid_series = df_event["eventID"].astype(str)
                if eid_series.isna().any():
                    report["errors"].append("event.parquet has null eventID values")
                if eid_series.duplicated().any():
                    report["errors"].append("event.parquet has duplicated eventID values")

                # Advisory "ID hygiene" check: flag eventID patterns that
                # look like mixed identifiers plus timestamps, which are
                # technically allowed in DwC but usually indicate that a
                # cleaner canonical ID plus remarks/provenance column
                # would be preferable.
                suspicious_mask = eid_series.str.contains(",", na=False) & eid_series.str.contains(
                    r"\d{4}-\d{2}-\d{2}", na=False
                )
                if bool(suspicious_mask.any()):
                    warnings.append(
                        "eventID values that combine commas and ISO-like dates detected; "
                        "consider deriving a canonical eventID column and preserving the "
                        "original value in eventRemarks or separate provenance tables."
                    )

                # All occurrence.eventID values should link to an existing event.eventID
                if "eventID" in df_occ.columns:
                    occ_eid = df_occ["eventID"].dropna().astype(str)
                    missing = sorted(set(occ_eid.unique()) - set(eid_series.unique()))
                    if missing:
                        report["errors"].append(
                            "occurrence.parquet has eventID values with no matching event.parquet: "
                            + ", ".join(list(missing)[:20])
                        )

                # Soft check: are eventDate values parseable as dates?
                if "eventDate" in df_event.columns:
                    parsed = pd.to_datetime(df_event["eventDate"], errors="coerce")
                    total = len(parsed)
                    if total:
                        invalid_frac = float(parsed.isna().mean())
                        if invalid_frac > 0.1:
                            warnings.append(
                                "event.eventDate has many values that do not parse cleanly as dates; "
                                "please check date formats in the canonical tables."
                            )

        if df_occ is not None:
            # occurrenceID should be present and (ideally) unique
            if "occurrenceID" not in df_occ.columns:
                report["errors"].append("occurrence.parquet missing occurrenceID column")
            else:
                occid_series = df_occ["occurrenceID"].astype(str)
                if occid_series.isna().any():
                    report["errors"].append("occurrence.parquet has null occurrenceID values")
                if occid_series.duplicated().any():
                    report["errors"].append("occurrence.parquet has duplicated occurrenceID values")

            # Soft vocabulary hint: basisOfRecord and occurrenceStatus
            # should generally use DwC recommended values; we surface
            # obvious deviations as warnings only.
            if "basisOfRecord" in df_occ.columns:
                allowed_bor = {
                    "HumanObservation",
                    "MachineObservation",
                    "MaterialSample",
                    "PreservedSpecimen",
                    "FossilSpecimen",
                    "LivingSpecimen",
                }
                vals = (
                    df_occ["basisOfRecord"].dropna().astype(str).unique().tolist()
                )
                bad = sorted({v for v in vals if v and v not in allowed_bor})
                if bad:
                    warnings.append(
                        "occurrence.basisOfRecord contains non-standard values (showing up to 5): "
                        + ", ".join(bad[:5])
                    )

            if "occurrenceStatus" in df_occ.columns:
                allowed_status = {"present", "absent"}
                vals = (
                    df_occ["occurrenceStatus"].dropna().astype(str).str.lower().unique().tolist()
                )
                bad = sorted({v for v in vals if v and v not in allowed_status})
                if bad:
                    warnings.append(
                        "occurrence.occurrenceStatus contains non-standard values (showing up to 5): "
                        + ", ".join(bad[:5])
                    )

            # Soft coordinate completeness/range check when coordinates are present.
            if "decimalLatitude" in df_occ.columns and "decimalLongitude" in df_occ.columns:
                lat = pd.to_numeric(df_occ["decimalLatitude"], errors="coerce")
                lon = pd.to_numeric(df_occ["decimalLongitude"], errors="coerce")
                total = len(df_occ)
                if total:
                    complete = (~lat.isna() & ~lon.isna()).mean()
                    if complete and complete < 0.5:
                        warnings.append(
                            "Less than half of occurrence records have both decimalLatitude and decimalLongitude; "
                            "consider whether coordinates should be provided more completely."
                        )
                    out_of_range = ((lat < -90) | (lat > 90) | (lon < -180) | (lon > 180))
                    if bool(out_of_range.any()):
                        warnings.append(
                            "Some occurrence coordinates fall outside expected latitude/longitude ranges; "
                            "please verify the coordinate system and units."
                        )

        if df_meas is not None:
            # measurementID should be unique where present
            if "measurementID" in df_meas.columns:
                mid_series = df_meas["measurementID"].astype(str)
                if mid_series.isna().any():
                    report["errors"].append("measurement_or_fact.parquet has null measurementID values")
                if mid_series.duplicated().any():
                    report["errors"].append("measurement_or_fact.parquet has duplicated measurementID values")

            # All measurement_or_fact.occurrenceID should resolve to occurrence.occurrenceID
            if df_occ is not None and "occurrenceID" in df_meas.columns and "occurrenceID" in df_occ.columns:
                meas_occ = df_meas["occurrenceID"].dropna().astype(str)
                occ_ids = df_occ["occurrenceID"].dropna().astype(str)
                missing = sorted(set(meas_occ.unique()) - set(occ_ids.unique()))
                if missing:
                    report["errors"].append(
                        "measurement_or_fact.parquet has occurrenceID values with no matching occurrence.parquet: "
                        + ", ".join(list(missing)[:20])
                    )

            # All measurement_or_fact.eventID should resolve to event.eventID
            if df_event is not None and "eventID" in df_meas.columns and "eventID" in df_event.columns:
                meas_eid = df_meas["eventID"].dropna().astype(str)
                evt_ids = df_event["eventID"].dropna().astype(str)
                missing = sorted(set(meas_eid.unique()) - set(evt_ids.unique()))
                if missing:
                    report["errors"].append(
                        "measurement_or_fact.parquet has eventID values with no matching event.parquet: "
                        + ", ".join(list(missing)[:20])
                    )
        if dwc_checks:
            report["dwc_checks"] = dwc_checks

        if warnings:
            report["warnings"] = warnings
        return report

    # Non-DwC branch: summarise any canonical parquet that exists.
    if not canonical_dir.exists():
        if warnings:
            report["warnings"] = warnings
        return report

    for p in canonical_dir.glob("*.parquet"):
        try:  # pragma: no cover - IO
            df = pd.read_parquet(p)
            report["canonical"][p.name] = {
                "rows": int(len(df)),
                "columns": list(df.columns),
            }
        except Exception as exc:  # pragma: no cover - defensive
            report["canonical"][p.name] = {"error": str(exc)}
            report["errors"].append(f"failed to read {p.name}: {exc}")

    if warnings:
        report["warnings"] = warnings
    return report


def _check_processed(dataset_dir: Path) -> dict:
    """Inspect processed Parquet tables for basic health and dtypes."""

    processed_dir = dataset_dir / "processed"
    rpt: dict[str, Any] = {"processed": {}, "object_dtypes": []}
    for p in processed_dir.glob("*.parquet"):
        try:  # pragma: no cover - IO
            df = pd.read_parquet(p)
        except Exception as e:  # pragma: no cover - defensive
            rpt["processed"][p.name] = {"error": str(e)}
            continue
        dtypes = {c: str(dt) for c, dt in df.dtypes.items()}
        rpt["processed"][p.name] = {"rows": int(len(df)), "dtypes": dtypes}
        objs = [c for c, dt in df.dtypes.items() if str(dt) == "object"]
        if objs:
            rpt["object_dtypes"].append({p.name: objs})
    return rpt


def _check_metadata(dataset_dir: Path) -> dict:
    """Validate presence and basic parseability of metadata artefacts.

    This checks that JSON/JSON-LD metadata files are well-formed and that
    any EML XML file we produced can be parsed. It is intentionally
    lightweight; deeper semantic checks belong in higher-level validation
    or FAIR scoring.
    """

    md_dir = dataset_dir / "metadata"
    result: dict[str, Any] = {"files": {}, "errors": []}

    if not md_dir.exists():
        result["errors"].append("missing metadata/ directory")
        return result

    def _check_json_file(name: str) -> None:
        p = md_dir / name
        if not p.exists():
            result["files"][name] = {"status": "missing"}
            return
        try:
            with open(p, "r", encoding="utf-8") as fh:
                json.load(fh)
            result["files"][name] = {"status": "ok"}
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"invalid JSON in {name}: {exc}"
            result["files"][name] = {"status": "error", "message": str(exc)}
            result["errors"].append(msg)

    # Core JSON metadata produced by the pipeline
    _check_json_file("manifest.json")
    _check_json_file("dataset_metadata.json")

    # Optional machine-oriented metadata
    _check_json_file("metadata.jsonld")
    _check_json_file("qa_report.json")

    # RO-Crate is written at dataset root, not inside metadata/
    crate_path = dataset_dir / "ro-crate-metadata.json"
    if crate_path.exists():
        try:
            with open(crate_path, "r", encoding="utf-8") as fh:
                json.load(fh)
            result["files"]["ro-crate-metadata.json"] = {"status": "ok"}
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"invalid JSON in ro-crate-metadata.json: {exc}"
            result["files"]["ro-crate-metadata.json"] = {
                "status": "error",
                "message": str(exc),
            }
            result["errors"].append(msg)
    else:
        result["files"]["ro-crate-metadata.json"] = {"status": "missing"}

    # EML XML: prefer curated, else draft if present
    eml_curated = md_dir / "eml_curated.xml"
    eml_draft = md_dir / "eml_draft.xml"
    eml_target: Path | None = None
    if eml_curated.exists():
        eml_target = eml_curated
        label = "eml_curated.xml"
    elif eml_draft.exists():
        eml_target = eml_draft
        label = "eml_draft.xml"
    else:
        label = "eml.xml"
        default_eml = md_dir / "eml.xml"
        if default_eml.exists():
            eml_target = default_eml

    if eml_target is None:
        result["files"][label] = {"status": "missing"}
    else:
        try:
            ET.parse(eml_target)
            result["files"][label] = {"status": "ok"}
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"invalid XML in {label}: {exc}"
            result["files"][label] = {"status": "error", "message": str(exc)}
            result["errors"].append(msg)

    return result


def run_validation_for_dataset(dataset_dir: Path) -> dict:

    """Run generic validation for a dataset directory.

    This function is intended to be called by thin dataset-level
    wrappers (e.g. ``datasets/<id>/etl/validate.py``). It inspects
    processed tables, canonical outputs, and metadata artefacts,
    returning a JSON-serialisable report structure.

    In addition to detailed sections, it populates a top-level
    ``summary`` block with a few booleans that indicate whether
    the dataset appears "ready to publish" according to simple
    checks (presence of canonical data, key metadata files, and
    at least a draft EML record).
    """

    report: dict[str, Any] = {"summary": {}}

    dataset_yaml_path = resolve_dataset_config_path(dataset_dir, explicit=None)
    cfg = _load_yaml(dataset_yaml_path)
    ds_errors, ds_warnings = validate_dataset_yaml(cfg, dataset_yaml_path)
    report_and_maybe_abort(ds_errors, ds_warnings, fatal=True)
    dataset_section = cfg.get("dataset", {})
    profile_id = dataset_section.get("profile")
    profile = _load_profile(dataset_dir, profile_id)
    if profile_id:
        profiles_dir = dataset_dir.parent / "profiles"
        profile_path = profiles_dir / f"{profile_id}.yaml"
        pr_errors, pr_warnings = validate_profile_yaml(profile, profile_path)
        # Profile issues are non-fatal for validation; they mainly affect
        # how we interpret standards.
        report_and_maybe_abort(pr_errors, pr_warnings, fatal=False)

    # Canonical (profile-aware)
    canonical_rpt = _check_canonical(dataset_dir, profile)
    report.update(canonical_rpt)

    # Processed tables
    report["processed"] = _check_processed(dataset_dir)

    # Metadata artefacts (manifest, EML, JSON-LD, RO-Crate, QA report)
    md_rpt = _check_metadata(dataset_dir)
    report["metadata"] = md_rpt

    # Optional Pandera checks driven by dataset config
    pandera_rpt = _check_pandera(dataset_dir, cfg)
    if pandera_rpt:
        report["pandera"] = pandera_rpt

    # Collect a flat list of validation error messages across
    # canonical, metadata, and optional Pandera checks so that the
    # top-level summary can expose an accurate error count.
    all_errors: list[str] = []
    all_errors.extend(canonical_rpt.get("errors", []))
    all_errors.extend(md_rpt.get("errors", []))
    if pandera_rpt:
        all_errors.extend(pandera_rpt.get("errors", []))
    report["errors"] = all_errors

    # Collect non-fatal advisory warnings (e.g. "ID hygiene" hints)
    # so that dashboards and humans can review them without affecting
    # the publish-ready status.
    all_warnings: list[str] = []
    all_warnings.extend(canonical_rpt.get("warnings", []))
    if all_warnings:
        report["warnings"] = all_warnings

    # ------------------------------------------------------------------
    # Publish-readiness summary
    # ------------------------------------------------------------------
    canon_files = (report.get("canonical") or {})
    has_canonical = bool(canon_files)

    # Lightweight row counts for the most important canonical tables,
    # so dashboards can show basic dataset size without re-parsing
    # Parquet themselves.
    evt_info = canon_files.get("event.parquet", {})
    occ_info = canon_files.get("occurrence.parquet", {})
    meas_info = canon_files.get("measurement_or_fact.parquet", {})
    n_events = int(evt_info.get("rows", 0) or 0)
    n_occurrences = int(occ_info.get("rows", 0) or 0)
    n_measurements = int(meas_info.get("rows", 0) or 0)

    md_files = (md_rpt.get("files") or {})
    has_manifest = md_files.get("manifest.json", {}).get("status") == "ok"
    has_dataset_meta = md_files.get("dataset_metadata.json", {}).get("status") == "ok"
    has_jsonld = md_files.get("metadata.jsonld", {}).get("status") == "ok"
    has_rocrate = md_files.get("ro-crate-metadata.json", {}).get("status") == "ok"

    # EML: curated or draft counts as "has_eml". We also classify
    # the metadata completeness status for human readers.
    has_eml = False
    eml_status = "missing"
    if md_files.get("eml_curated.xml", {}).get("status") == "ok":
        has_eml = True
        eml_status = "curated"
    elif md_files.get("eml_draft.xml", {}).get("status") == "ok":
        has_eml = True
        eml_status = "draft"
    elif md_files.get("eml.xml", {}).get("status") == "ok":
        has_eml = True
        eml_status = "legacy"

    if not has_eml:
        metadata_completeness = "missing"
    elif eml_status == "curated":
        metadata_completeness = "curated"
    else:
        metadata_completeness = "minimal"

    # Standards information derived from the profile: which data
    # standard is in use, which metadata standards were requested,
    # and which ontologies are referenced.
    stds = (profile.get("defaults") or {}).get("standards") or {}
    data_std = stds.get("data") if isinstance(stds, dict) else None
    md_stds_raw = stds.get("metadata") if isinstance(stds, dict) else None
    if isinstance(md_stds_raw, str):
        metadata_standards = [md_stds_raw]
    elif isinstance(md_stds_raw, list):
        metadata_standards = [str(s) for s in md_stds_raw]
    else:
        metadata_standards = []

    ontologies_cfg = profile.get("ontologies") or {}
    ontologies_used = list(ontologies_cfg.keys()) if isinstance(ontologies_cfg, dict) else []

    # Derive a simple DwC validation status so dashboards can show a
    # clear "DwC OK / issues / not applicable" flag without re-
    # interpreting the full error list.
    dwc_status = "not_applicable"
    data_std_norm = (str(data_std).strip().lower() if data_std else None)
    dwc_checks = canonical_rpt.get("dwc_checks")
    if data_std_norm in {"darwin_core", "dwc"}:
        if not dwc_checks:
            dwc_status = "not_run"
        else:
            required_tables = ["event", "occurrence", "measurement_or_fact"]
            have_required = all(t in dwc_checks for t in required_tables)
            required_ok = all(
                dwc_checks[t].get("has_table") and dwc_checks[t].get("required_terms_present")
                for t in required_tables
                if t in dwc_checks
            )
            if have_required and required_ok and not report.get("errors"):
                dwc_status = "ok"
            else:
                dwc_status = "issues"

    # Dataset identity for dashboards; fall back gracefully if fields
    # are missing from the config.
    dataset_id = str(dataset_section.get("id") or "")
    dataset_title = str(dataset_section.get("title") or "")

    report["summary"] = {
        "dataset_id": dataset_id,
        "dataset_title": dataset_title,
        "profile": profile_id,
        "has_canonical": has_canonical,
        "n_events": n_events,
        "n_occurrences": n_occurrences,
        "n_measurements": n_measurements,
        "has_manifest": has_manifest,
        "has_dataset_metadata": has_dataset_meta,
        "has_eml": has_eml,
        "eml_status": eml_status,
        "metadata_completeness": metadata_completeness,
        "has_jsonld": has_jsonld,
        "has_rocrate": has_rocrate,
        "data_standard": data_std,
        "metadata_standards": metadata_standards,
        "ontologies_used": ontologies_used,
        "dwc_validation_status": dwc_status,
        "n_errors": int(len(report.get("errors") or [])),
        "n_warnings": int(len(report.get("warnings") or [])) if "warnings" in report else 0,
    }

    # A very simple readiness flag: all key pieces present and no
    # hard errors recorded. This can be refined per profile later.
    required_bits = [
        has_canonical,
        has_manifest,
        has_dataset_meta,
        has_eml,
    ]
    report["summary"]["ready_to_publish"] = bool(all(required_bits) and not report["summary"]["n_errors"])

    # A lightweight "standards" section mirrors the most important
    # pieces of the profile in a structured way for dashboards.
    standards_section: dict[str, Any] = {}
    if data_std is not None:
        standards_section["data"] = data_std
    if metadata_standards:
        standards_section["metadata"] = metadata_standards
    if ontologies_used:
        standards_section["ontologies"] = ontologies_used
    if standards_section:
        report["standards"] = standards_section

    return report


def _check_pandera(dataset_dir: Path, cfg: Dict[str, Any]) -> dict:
    """Run optional Pandera validation on processed tables.

    This is entirely config-driven. If ``dataset.yaml`` contains a
    section like::

        validation:
        processed:
            soil_measurements:
            dtypes:
                soil_moisture_pct: float
                porewater_ec_ms_m: float
            ranges:
                soil_moisture_pct: [0, 100]

    then we will build a Pandera schema for ``processed/soil_measurements.parquet``
    and report whether it passes. If no such config is present, this
    returns an empty dict and is effectively a no-op.
    """

    validation_cfg = (cfg.get("validation") or {}).get("processed") or {}
    if not validation_cfg:
        return {}

    processed_dir = dataset_dir / "processed"
    result: dict[str, Any] = {"processed": {}, "errors": []}

    for table_name, rules in validation_cfg.items():
        path = processed_dir / f"{table_name}.parquet"
        if not path.exists():
            msg = f"Pandera validation: missing processed table {table_name}.parquet"
            result["processed"][table_name] = {"status": "missing"}
            result["errors"].append(msg)
            continue

        try:  # pragma: no cover - IO
            df = pd.read_parquet(path)
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"Pandera validation: failed to read {table_name}.parquet: {exc}"
            result["processed"][table_name] = {"status": "error", "message": str(exc)}
            result["errors"].append(msg)
            continue

        dtypes_cfg = rules.get("dtypes") or {}
        ranges_cfg = rules.get("ranges") or {}
        if not dtypes_cfg:
            # Nothing to enforce; skip quietly
            continue

        schema = make_schema_from_config(dtypes_cfg, ranges_cfg)
        try:
            schema.validate(df, lazy=True)
            result["processed"][table_name] = {
                "status": "ok",
                "rows": int(len(df)),
            }
        except pa_errors.SchemaErrors as e:  # pragma: no cover - depends on data
            failure_cases = e.failure_cases
            cols = sorted({str(c) for c in failure_cases.get("column", []) if c})
            msg = f"Pandera validation failed for {table_name}.parquet"
            result["processed"][table_name] = {
                "status": "failed",
                "rows": int(len(df)),
                "n_failures": int(len(failure_cases)),
                "failure_columns": cols,
            }
            result["errors"].append(msg)

    return result


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for running validation on a dataset.

    Example usage from the project root (data-automation/):

        python -m etl.validate --dataset-dir datasets/walking_forest
    """

    parser = argparse.ArgumentParser(
        description=(
            "Run generic validation for a dataset directory and write a "
            "QA report as JSON."
        ),
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        required=True,
        help=(
            "Path to the dataset directory (e.g. datasets/walking_forest). "
            "This directory must contain dataset.yaml."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path to write the QA report JSON. "
            "Defaults to <dataset_dir>/metadata/qa_report.json."
        ),
    )

    args = parser.parse_args(argv)
    dataset_dir = args.dataset_dir.resolve()
    report = run_validation_for_dataset(dataset_dir)

    out_path = args.output or (dataset_dir / "metadata" / "qa_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Wrote validation report to", out_path)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
