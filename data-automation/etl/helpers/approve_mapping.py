"""Approve a suggested mapping and copy it to the approved mapping file.

This CLI validates the suggested mapping file, checks that referenced
source tables/columns exist in the dataset `processed/` or `staging/`
outputs, stamps approval metadata and writes the approved mapping to
`mappings/<standard>_standard.yaml` (e.g. `dwc_standard.yaml`). An
audit copy is written to `mappings/history/`.

Usage:
    python -m etl.helpers.approve_mapping --dataset-dir datasets/foo

"""
from __future__ import annotations

from pathlib import Path
import argparse
import shutil
import yaml
from datetime import datetime
import getpass
from typing import Dict, Any, Set

from etl.helpers.config_validation import validate_mapping_yaml, report_and_maybe_abort
import pandas as pd
import re


def _find_suggested_file(dataset_dir: Path, standard: str) -> Path | None:
    cand = dataset_dir / "mappings"
    names = [f"{standard}_standard_suggested.yaml", f"{standard}_suggested.yaml", f"{standard}_standard_suggested.yaml"]
    for n in names:
        p = cand / n
        if p.exists():
            return p
    return None


def _collect_referenced_columns(mapping: Dict[str, Any]) -> Dict[str, Set[str]]:
    refs: Dict[str, Set[str]] = {}
    tables = mapping.get("tables") or {}
    if not isinstance(tables, dict):
        return refs
    for tbl, tbl_map in tables.items():
        s: Set[str] = set()
        if not isinstance(tbl_map, dict):
            refs[tbl] = s
            continue
        # event/occurrence simple mappings
        for block in ("event", "occurrence"):
            b = tbl_map.get(block) or {}
            if isinstance(b, dict):
                for v in b.values():
                    if isinstance(v, str):
                        s.add(v)
                    elif isinstance(v, dict) and "source" in v and isinstance(v.get("source"), str):
                        s.add(v.get("source"))
        # measurements list
        for m in tbl_map.get("measurements") or []:
            if isinstance(m, dict):
                src = m.get("source")
                if isinstance(src, str):
                    s.add(src)
        refs[tbl] = s
    return refs


def _check_tables_and_columns(dataset_dir: Path, refs: Dict[str, Set[str]]) -> Dict[str, Dict[str, Any]]:
    problems: Dict[str, Dict[str, Any]] = {}
    processed = dataset_dir / "processed"
    staging = dataset_dir / "staging"
    for tbl, cols in refs.items():
        # prefer processed then staging
        candidate_paths = [processed / tbl, staging / tbl]
        found = None
        for p in candidate_paths:
            if p.exists():
                found = p
                break
        if not found:
            problems[tbl] = {"missing_table": True, "missing_columns": list(cols)}
            continue
        try:
            if found.suffix.lower() == ".parquet":
                df = pd.read_parquet(found)
            else:
                # guard: try read_parquet then fallback
                df = pd.read_parquet(found)
        except Exception:
            problems[tbl] = {"error": f"unable to read {found}"}
            continue
        present = set(str(c) for c in df.columns)
        missing = [c for c in cols if c not in present]
        if missing:
            problems[tbl] = {"missing_table": False, "missing_columns": missing}
    return problems


def approve_mapping(dataset_dir: Path, standard: str = "dwc", suggested: Path | None = None, approver: str | None = None, force: bool = False) -> Path:
    suggested = Path(suggested) if suggested else None
    if suggested is None:
        suggested = _find_suggested_file(dataset_dir, standard)
        if suggested is None:
            raise SystemExit(f"No suggested mapping found for standard '{standard}' in {dataset_dir}/mappings")

    try:
        doc = yaml.safe_load(suggested.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise SystemExit(f"Failed to read suggested mapping: {exc}")

    # Basic structure validation
    errors, warnings = validate_mapping_yaml(doc, suggested)
    if errors:
        for e in errors:
            print("[approve] ERROR:", e)
        raise SystemExit("Suggested mapping validation failed; fix the draft first.")

    # Check referenced columns in processed/staging
    refs = _collect_referenced_columns(doc)
    # If the dataset config has cleaning disabled, warn the author when the
    # suggested mapping appears to reference cleaned/canonical-looking column
    # names. This helps avoid the common mismatch where authors approve drafts
    # with canonical names while the pipeline will not clean source columns.
    try:
        ds_cfg_path = dataset_dir / "dataset.yaml"
        cleaning_enabled = True
        if ds_cfg_path.exists():
            try:
                ds_cfg = yaml.safe_load(ds_cfg_path.read_text(encoding="utf-8")) or {}
                cleaning_enabled = bool(ds_cfg.get("cleaning", {}).get("enabled", True))
            except Exception:
                cleaning_enabled = True
        if not cleaning_enabled:
            def _looks_cleaned(col: str) -> bool:
                if not isinstance(col, str):
                    return False
                # Typical cleaned names: lowercase alnums with underscores
                if re.match(r'^[a-z0-9_]+$', col) and ('_' in col):
                    return True
                # Also flag common canonical suffixes even without underscores
                if re.search(r'_(count|id|value|percent|mean|std|min|max|sum|measurement|date)$', col):
                    return True
                return False

            cleaned_refs: list[tuple[str, str]] = []
            for t, cols in refs.items():
                for c in cols:
                    if _looks_cleaned(c):
                        cleaned_refs.append((t, c))
            if cleaned_refs:
                print("[approve] WARNING: dataset 'cleaning.enabled' is False but suggested mapping references cleaned-looking column names; this may cause mismatches during approval/export.")
                for t, c in cleaned_refs[:20]:
                    print(f"  - {t}: {c}")
                print("  Tip: enable cleaning in dataset.yaml or update the suggested mapping to use raw column names.")
    except Exception:
        # Non-fatal: do not prevent approval because of the warning check
        pass
    problems = _check_tables_and_columns(dataset_dir, refs)
    bad = {t: p for t, p in problems.items() if p}
    if bad:
        print("[approve] Found missing tables/columns:")
        for t, info in bad.items():
            print(f" - {t}: {info}")
        raise SystemExit("Approval aborted: fix missing source tables/columns or adjust mapping.")

    # prepare approved path
    approved_dir = dataset_dir / "mappings"
    approved_dir.mkdir(parents=True, exist_ok=True)
    approved_path = approved_dir / f"{standard}_standard.yaml"
    if approved_path.exists() and not force:
        raise SystemExit(f"Approved mapping already exists at {approved_path}; use --force to overwrite")

    # stamp approval metadata
    approver = approver or getpass.getuser() or "unknown"
    meta = doc.get("meta") or {}
    meta["approved_by"] = approver
    meta["approved_at"] = datetime.now().astimezone().isoformat()
    meta["approved_from"] = suggested.name
    # Approved mappings must reference canonical column names
    # and we record that contract explicitly in metadata.
    meta["column_schema"] = "canonical"
    doc["meta"] = meta

    # write audit copy
    history_dir = approved_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    audit_name = f"{standard}_standard_approved_{ts}.yaml"
    audit_path = history_dir / audit_name
    audit_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # copy approved file
    approved_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Approved mapping written to: {approved_path}")
    print(f"Audit copy written to: {audit_path}")
    return approved_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Approve a suggested mapping for a dataset and write approved mapping.")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--standard", default="dwc")
    parser.add_argument("--suggested", type=Path, default=None, help="Path to suggested mapping (optional)")
    parser.add_argument("--approver", default=None, help="Name of approver to stamp")
    parser.add_argument("--force", action="store_true", help="Overwrite existing approved mapping if present")
    args = parser.parse_args(argv)

    approve_mapping(args.dataset_dir.resolve(), standard=args.standard, suggested=args.suggested, approver=args.approver, force=args.force)


if __name__ == "__main__":
    main()
