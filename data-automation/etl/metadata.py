"""Shared FAIR metadata utilities and dataset-level metadata engine.

This module centralises dataset-agnostic metadata logic so that
individual datasets only need thin wrappers. It is responsible for:

- Building a simple file manifest over canonical tables and key
  metadata artefacts.
- Writing minimal dataset-level JSON metadata derived from
  ``dataset.yaml``.
- Emitting EML, JSON-LD, and RO-Crate representations, as requested
  by the dataset profile configuration.

Typical dataset wrapper usage (e.g. datasets/<id>/etl/metadata.py):

    from pathlib import Path
    from etl import metadata as etl_metadata

    DATASET_DIR = Path(__file__).resolve().parents[1]
    etl_metadata.generate_metadata_for_dataset(DATASET_DIR, fair_level="recommended")

This keeps the FAIR metadata engine in one place while remaining
config-driven and reusable across datasets.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import hashlib
import json
import re
from typing import Any, Dict, List
from datetime import datetime, timezone
import yaml
import xml.etree.ElementTree as ET

from etl.helpers.config_validation import (
    resolve_dataset_config_path,
    validate_dataset_yaml,
    validate_profile_yaml,
    report_and_maybe_abort,
)


# ---------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------
# JSON-LD helper (shared across entrypoints)
# ---------------------------------------------------------------------


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_jsonld(
    dataset_cfg: dict,
    out_dir: Path,
    provenance: list[dict],
    n_rows: int,
) -> None:
    """Create a small JSON-LD record with basic FAIR fields.

    Parameters
    ----------
    dataset_cfg:
        Parsed ``dataset.yaml`` (or equivalent) configuration.
        We expect an optional ``jsonld`` section for overrides.
    out_dir:
        Destination directory (typically ``metadata/``).
    provenance:
        List of input file descriptors, each containing at least
        ``path``, ``sizeBytes``, and ``sha256``.
    n_rows:
        Optional total row count for the main data product
        (use 0 if not known).
    """

    jsonld_cfg = dataset_cfg.get("jsonld", {}) or {}

    meta = {
        "@context": jsonld_cfg.get("context", ["https://schema.org/"]),
        "@type": jsonld_cfg.get("type", "Dataset"),
        "name": (dataset_cfg.get("dataset") or {}).get("title")
        or (dataset_cfg.get("dataset") or {}).get("id")
        or "unknown-dataset",
        "description": dataset_cfg.get("description", ""),
        "keywords": jsonld_cfg.get("keywords", []),
        "license": jsonld_cfg.get("license", ""),
        "publisher": jsonld_cfg.get("publisher", ""),
        "dateModified": datetime.now(timezone.utc).isoformat(),
        "numberOfRows": int(n_rows),
        "provenance": provenance,
    }
    _write_json(out_dir / "metadata.jsonld", meta)


# ---------------------------------------------------------------------
# Dataset-level metadata engine (manifest + exports)
# ---------------------------------------------------------------------


def _load_profile(dataset_dir: Path, profile_id: str | None) -> Dict[str, Any]:
    if not profile_id:
        return {}
    profiles_dir = dataset_dir.parent / "profiles"
    return _load_yaml(profiles_dir / f"{profile_id}.yaml")


def _load_human_metadata(dataset_dir: Path, dataset_id: str) -> Dict[str, Any]:
    """Load optional human-authored metadata YAML for a dataset.

    Expected location: ``metadata/<dataset_id>_metadata.yaml``.
    Falls back to any ``*metadata.yaml`` file if the named file
    is absent.
    """

    metadata_dir = dataset_dir / "metadata"
    specific = metadata_dir / f"{dataset_id}_metadata.yaml"
    if specific.exists():
        return _load_yaml(specific)

    if metadata_dir.exists():
        for p in metadata_dir.glob("*metadata.yaml"):
            return _load_yaml(p)
    return {}


def build_manifest(dataset_dir: Path) -> Dict[str, Any]:
    """Create a manifest over canonical tables and key metadata files."""

    metadata_dir = dataset_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    config = _load_yaml(dataset_dir / "dataset.yaml")
    dataset_id = (config.get("dataset") or {}).get("id", dataset_dir.name)

    files: List[Dict[str, Any]] = []

    canonical_dir = dataset_dir / "canonical"
    if canonical_dir.exists():
        for p in sorted(canonical_dir.glob("*.parquet")):
            files.append(
                {
                    "path": str(p.relative_to(dataset_dir)),
                    "kind": "data",
                    "sha256": _sha256_file(p),
                    "size_bytes": int(p.stat().st_size),
                }
            )

    qa = metadata_dir / "qa_report.json"
    if qa.exists():
        files.append(
            {
                "path": str(qa.relative_to(dataset_dir)),
                "kind": "qa_report",
                "sha256": _sha256_file(qa),
                "size_bytes": int(qa.stat().st_size),
            }
        )

    manifest = {"dataset_id": dataset_id, "files": files}

    out = metadata_dir / "manifest.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def write_dataset_metadata(dataset_dir: Path, fair_level: str) -> Dict[str, Any]:
    """Write minimal dataset-level metadata derived from dataset.yaml."""

    config = _load_yaml(dataset_dir / "dataset.yaml")
    d = config.get("dataset", {})

    meta = {
        "id": d.get("id", dataset_dir.name),
        "title": d.get("title", dataset_dir.name),
        "profile": d.get("profile"),
        "fair_level": fair_level,
    }

    metadata_dir = dataset_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    out = metadata_dir / "dataset_metadata.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def build_dataset_info(
    dataset_dir: Path,
    manifest: Dict[str, Any],
    fair_level: str,
) -> Dict[str, Any]:
    """Assemble a standard-agnostic dataset_info structure."""

    cfg = _load_yaml(dataset_dir / "dataset.yaml")
    d = cfg.get("dataset", {})
    dataset_id = d.get("id", dataset_dir.name)
    profile_id = d.get("profile")

    profile = _load_profile(dataset_dir, profile_id)
    human_md = _load_human_metadata(dataset_dir, dataset_id)

    info: Dict[str, Any] = {
        "id": dataset_id,
        "title": d.get("title", dataset_dir.name),
        "profile_id": profile_id,
        "fair_level": fair_level,
        "config": cfg,
        "profile": profile,
        "human_metadata": human_md,
        "manifest": manifest,
    }

    return info


def write_eml(
    dataset_dir: Path,
    dataset_info: Dict[str, Any],
    out_path: Path | None = None,
) -> Path:
    """Write a minimal EML file from the dataset_info model."""

    metadata_dir = dataset_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    did = dataset_info["id"]
    title = dataset_info.get("title", did)
    human = dataset_info.get("human_metadata") or {}

    eml_attrs = {
        "packageId": did,
        "system": "lter-life-pipeline",
        "xmlns:eml": "eml://ecoinformatics.org/eml-2.2.0",
    }
    root = ET.Element("eml:eml", eml_attrs)

    dataset_el = ET.SubElement(root, "dataset")

    t_el = ET.SubElement(dataset_el, "title")
    t_el.text = title

    desc = human.get("description")
    if desc:
        abstract = ET.SubElement(dataset_el, "abstract")
        para = ET.SubElement(abstract, "para")
        para.text = str(desc)

    for contrib in human.get("contributors", []) or []:
        creator = ET.SubElement(dataset_el, "creator")
        ind_name = ET.SubElement(creator, "individualName")
        name_el = ET.SubElement(ind_name, "surName")
        name_el.text = str(contrib.get("name"))
        org = contrib.get("affiliation")
        if org:
            org_el = ET.SubElement(creator, "organizationName")
            org_el.text = str(org)

    cov = human.get("spatial_scope") or {}
    t_cov = human.get("temporal_scope") or {}
    if cov or t_cov:
        coverage = ET.SubElement(dataset_el, "coverage")
        if cov:
            geo = ET.SubElement(coverage, "geographicCoverage")
            if cov.get("location_name"):
                gname = ET.SubElement(geo, "geographicDescription")
                gname.text = str(cov.get("location_name"))
        if t_cov:
            dates = t_cov.get("sampling_dates") or []

            # EML requires calendarDate to be a year (YYYY) or
            # full date (YYYY-MM-DD). Filter out obvious
            # placeholders so we don't emit invalid EML that
            # ezEML will reject.
            valid_dates: List[str] = []
            for d in dates:
                if not d:
                    continue
                s = str(d).strip()
                # Skip placeholder-like values such as "<start date>".
                if s.startswith("<") and s.endswith(">"):
                    continue
                if re.fullmatch(r"\d{4}", s) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                    valid_dates.append(s)

            if valid_dates:
                temp = ET.SubElement(coverage, "temporalCoverage")
                begin = ET.SubElement(temp, "singleDateTime")
                begin_el = ET.SubElement(begin, "calendarDate")
                begin_el.text = valid_dates[0]

    lic = human.get("license")
    if lic:
        ir = ET.SubElement(dataset_el, "intellectualRights")
        para = ET.SubElement(ir, "para")
        para.text = str(lic)

    kws = human.get("keywords") or []
    if kws:
        kwset = ET.SubElement(dataset_el, "keywordSet")
        for kw in kws:
            kw_el = ET.SubElement(kwset, "keyword")
            kw_el.text = str(kw)

    # Minimal methods stub: safe, generic description that
    # signals draft status but gives ezEML a methods section
    # to work with. Prefer a human-written methods summary
    # if present in the YAML metadata.
    methods_text = None
    human_methods = human.get("methods") or {}
    if isinstance(human_methods, dict):
        # e.g. methods: { field_protocol: "..." }
        methods_text = human_methods.get("field_protocol")
    elif isinstance(human_methods, str):
        methods_text = human_methods

    if not methods_text:
        methods_text = (
            "Data were processed using an automated FAIRification pipeline. "
            "This is a draft methods description intended for further curation."
        )

    methods_el = ET.SubElement(dataset_el, "methods")
    step_el = ET.SubElement(methods_el, "methodStep")
    desc_el = ET.SubElement(step_el, "description")
    para_el = ET.SubElement(desc_el, "para")
    para_el.text = str(methods_text)

    manifest = dataset_info.get("manifest") or {}
    for f in manifest.get("files", []):
        if f.get("kind") != "data":
            continue
        path = f.get("path")
        if not path:
            continue

        dt = ET.SubElement(dataset_el, "dataTable")
        en = ET.SubElement(dt, "entityName")
        en.text = path

        phys = ET.SubElement(dt, "physical")
        obj = ET.SubElement(phys, "objectName")
        obj.text = path

        fmt = ET.SubElement(phys, "dataFormat")
        # Use textFormat only for obvious text-like files; for
        # columnar/binary formats such as Parquet, fall back to
        # externallyDefinedFormat so the EML stays honest and
        # ezEML-friendly.
        if isinstance(path, str) and path.lower().endswith(".parquet"):
            ext = ET.SubElement(fmt, "externallyDefinedFormat")
            fmt_name = ET.SubElement(ext, "formatName")
            fmt_name.text = "Apache Parquet"
        else:
            textfmt = ET.SubElement(fmt, "textFormat")
            recdelim = ET.SubElement(textfmt, "recordDelimiter")
            recdelim.text = "\\n"

    tree = ET.ElementTree(root)
    if out_path is None:
        out_path = metadata_dir / "eml.xml"
    tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
    return out_path


def emit_eml_metadata(dataset_dir: Path, dataset_info: Dict[str, Any]) -> None:
    """Emit EML, respecting curated vs draft workflow."""

    metadata_dir = dataset_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    curated_path = metadata_dir / "eml_curated.xml"
    if curated_path.exists():
        print("Found curated EML at", curated_path)
        print(
            "Pipeline will NOT overwrite this file. To regenerate a draft, "
            "delete eml_curated.xml and rerun the metadata step.",
        )
        return

    draft_path = metadata_dir / "eml_draft.xml"
    out = write_eml(dataset_dir, dataset_info, out_path=draft_path)
    print("Wrote EML draft to", out)

    ezeml_url = "https://ezeml.edirepository.org/"
    instructions_path = metadata_dir / "ezEML_generator_instructions.txt"
    instructions_text = (
        "About this EML file\n\n"
        "eml_draft.xml was generated automatically by the LTER-LIFE ETL pipeline.\n\n"
        "It is a minimal metadata draft that is meant to be completed and "
        "finalised in ezEML.\n\n"
        "Complete the metadata in ezEML\n\n"
        "1. Go to: "
        f"{ezeml_url}\n"
        "2. Create a new dataset by importing an existing EML file.\n"
        "3. Upload eml_draft.xml from this metadata/ folder.\n\n"
        "In ezEML, complete the required dataset-level information, including:\n\n"
        "- Contact (with email address)\n"
        "- Temporal coverage\n"
        "- Project information\n"
        "- Optional but recommended: ORCID IDs for creators\n\n"
        "When ezEML asks for data tables:\n\n"
        "- Upload the CSV exports produced by the pipeline (e.g. Darwin Core or "
        "other standard CSV files).\n"
        "- ezEML will guide you through any remaining required fields (e.g. table "
        "descriptions, record counts, checksums).\n\n"
        "Finalising\n\n"
        "1. Export the completed metadata from ezEML and save it in this folder "
        "as: eml_curated.xml\n\n"
        "eml_curated.xml is the final, repository-ready metadata record.\n\n"
        "If the pipeline is run again, only draft metadata is regenerated. "
        "Curated metadata files such as eml_curated.xml are not modified or "
        "overwritten.\n"
    )
    try:
        metadata_dir.mkdir(parents=True, exist_ok=True)
        instructions_path.write_text(instructions_text, encoding="utf-8")
        print("Wrote ezEML instructions to", instructions_path)
    except Exception as exc:  # pragma: no cover - defensive
        print("Warning: failed to write ezEML instructions:", exc)


def emit_jsonld_metadata(dataset_dir: Path, dataset_info: Dict[str, Any]) -> None:
    """Emit JSON-LD metadata next to the dataset outputs."""

    cfg = dataset_info.get("config") or {}
    manifest = dataset_info.get("manifest") or {}
    metadata_dir = dataset_dir / "metadata"

    provenance: List[Dict[str, Any]] = []
    for f in manifest.get("files", []):
        if f.get("kind") != "data":
            continue
        prov = {
            "path": f.get("path"),
            "sizeBytes": f.get("size_bytes"),
            "sha256": f.get("sha256"),
            "kind": f.get("kind"),
        }
        provenance.append(prov)

    try:
        write_jsonld(cfg, metadata_dir, provenance, n_rows=0)
        print("Wrote JSON-LD metadata to", metadata_dir / "metadata.jsonld")
    except Exception as exc:  # pragma: no cover - defensive
        print("Failed to write JSON-LD metadata:", exc)


def emit_rocrate_metadata(dataset_dir: Path, dataset_info: Dict[str, Any]) -> None:
    """Emit a minimal RO-Crate metadata file for the dataset."""

    cfg = dataset_info.get("config") or {}
    human = dataset_info.get("human_metadata") or {}
    manifest = dataset_info.get("manifest") or {}

    crate_path = dataset_dir / "ro-crate-metadata.json"

    dataset_id = dataset_info.get("id") or dataset_dir.name
    title = dataset_info.get("title") or dataset_id

    dataset_entity: Dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "name": title,
        "identifier": dataset_id,
    }

    desc = human.get("description") or cfg.get("description")
    if desc:
        dataset_entity["description"] = desc

    lic = human.get("license") or (cfg.get("jsonld", {}) or {}).get("license")
    if lic:
        dataset_entity["license"] = lic

    kws = human.get("keywords") or (cfg.get("jsonld", {}) or {}).get("keywords") or []
    if kws:
        dataset_entity["keywords"] = kws

    graph: List[Dict[str, Any]] = []
    person_ids: List[Dict[str, str]] = []
    for idx, contrib in enumerate(human.get("contributors", []) or []):
        name = contrib.get("name")
        if not name:
            continue
        pid = f"#person-{idx+1}"
        person = {
            "@id": pid,
            "@type": "Person",
            "name": name,
        }
        org = contrib.get("affiliation")
        if org:
            person["affiliation"] = org
        graph.append(person)
        person_ids.append({"@id": pid})

    if person_ids:
        dataset_entity["author"] = person_ids

    has_parts: List[Dict[str, str]] = []
    for f in manifest.get("files", []):
        path = f.get("path")
        if not path:
            continue
        size = f.get("size_bytes")
        sha = f.get("sha256")

        file_ent: Dict[str, Any] = {
            "@id": path,
            "@type": "File",
        }
        if size is not None:
            file_ent["contentSize"] = size
        if sha:
            file_ent["sha256"] = sha

        ext = Path(path).suffix.lower()
        if ext == ".parquet":
            file_ent["encodingFormat"] = "application/x-parquet"
        elif ext in {".csv", ".tsv"}:
            file_ent["encodingFormat"] = "text/csv"

        graph.append(file_ent)
        has_parts.append({"@id": path})

    if has_parts:
        dataset_entity["hasPart"] = has_parts

    meta_ent = {
        "@id": "ro-crate-metadata.json",
        "@type": "CreativeWork",
        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        "about": {"@id": "./"},
        "dateCreated": datetime.now(timezone.utc).isoformat(),
    }

    graph.insert(0, dataset_entity)
    graph.insert(0, meta_ent)

    crate_obj = {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": graph,
    }

    try:
        crate_path.write_text(json.dumps(crate_obj, indent=2), encoding="utf-8")
        print("Wrote RO-Crate metadata to", crate_path)
    except Exception as exc:  # pragma: no cover - defensive
        print("Failed to write RO-Crate metadata:", exc)


def emit_metadata(
    dataset_dir: Path,
    dataset_info: Dict[str, Any],
    metadata_std: str | List[str] | None,
) -> None:
    """Dispatch metadata export based on requested standard(s)."""

    if not metadata_std:
        return

    if isinstance(metadata_std, str):
        requested = [metadata_std]
    elif isinstance(metadata_std, list):
        requested = metadata_std
    else:
        print("Unrecognised metadata standards specification:", metadata_std)
        return

    exporters = {
        "eml": emit_eml_metadata,
        "jsonld": emit_jsonld_metadata,
        "rocrate": emit_rocrate_metadata,
    }

    aliases = {
        "eml": "eml",
        "json-ld": "jsonld",
        "jsonld": "jsonld",
        "ro-crate": "rocrate",
        "ro_crate": "rocrate",
        "rocrate": "rocrate",
    }

    for std in requested:
        key = str(std).strip().lower()
        std_key = aliases.get(key, key)
        handler = exporters.get(std_key)
        if handler is None:
            print(f"Metadata standard '{std}' is not supported yet; skipping.")
            continue
        handler(dataset_dir, dataset_info)


def generate_metadata_for_dataset(
    dataset_dir: Path,
    fair_level: str = "recommended",
) -> Dict[str, Any]:
    """High-level entrypoint: generate FAIR metadata for a dataset.

    This writes ``manifest.json``, ``dataset_metadata.json``, and
    any metadata standards (EML, JSON-LD, RO-Crate) requested by
    the dataset profile configuration. Returns the internal
    ``dataset_info`` structure for further use if desired.
    """

    # Validate core config and profile before proceeding.
    dataset_yaml_path = resolve_dataset_config_path(dataset_dir, explicit=None)
    cfg = _load_yaml(dataset_yaml_path)
    ds_errors, ds_warnings = validate_dataset_yaml(cfg, dataset_yaml_path)
    report_and_maybe_abort(ds_errors, ds_warnings, fatal=True)

    manifest = build_manifest(dataset_dir)
    write_dataset_metadata(dataset_dir, fair_level=fair_level)
    dataset_info = build_dataset_info(
        dataset_dir=dataset_dir,
        manifest=manifest,
        fair_level=fair_level,
    )

    profile = dataset_info.get("profile") or {}
    profile_id = dataset_info.get("profile_id")
    if profile_id:
        profiles_dir = dataset_dir.parent / "profiles"
        profile_path = profiles_dir / f"{profile_id}.yaml"
        pr_errors, pr_warnings = validate_profile_yaml(profile, profile_path)
        report_and_maybe_abort(pr_errors, pr_warnings, fatal=False)
    stds = (profile.get("defaults") or {}).get("standards") or {}
    metadata_std = stds.get("metadata") if isinstance(stds, dict) else None

    emit_metadata(dataset_dir, dataset_info, metadata_std=metadata_std)

    metadata_dir = dataset_dir / "metadata"
    print(
        "Wrote manifest with",
        len(manifest["files"]),
        "files to",
        metadata_dir / "manifest.json",
    )
    print(
        "Wrote dataset metadata to",
        metadata_dir / "dataset_metadata.json",
    )

    return dataset_info


def main(argv: List[str] | None = None) -> None:
    """CLI entrypoint for generating FAIR metadata for a dataset.

    Example usage from the project root (data-automation/):

        python -m etl.metadata --dataset-dir datasets/walking_forest \
            --fair-level recommended
    """

    parser = argparse.ArgumentParser(
        description=(
            "Generate FAIR metadata (manifest, dataset_metadata.json, "
            "and EML/JSON-LD/RO-Crate as configured) for a dataset."
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
        "--fair-level",
        default="recommended",
        help=(
            "Fairness/metadata richness level to record in "
            "dataset_metadata.json (e.g. minimal, recommended, full)."
        ),
    )

    args = parser.parse_args(argv)
    dataset_dir = args.dataset_dir.resolve()

    generate_metadata_for_dataset(dataset_dir, fair_level=str(args.fair_level))


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
