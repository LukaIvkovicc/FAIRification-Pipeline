"""Lightweight validation helpers for ETL configuration files.

These helpers are intentionally simple and dependency-free. They check
for the presence of required keys and return structured errors/warnings
so callers can fail fast with clear messages if/when configs are broken.

They are *not* strict schemas - they are just  guards to catch the most
common misconfigurations early in the pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple


ValidationResult = Tuple[List[str], List[str]]  # (errors, warnings)


def resolve_dataset_config_path(dataset_dir: Path, explicit: Path | None = None) -> Path:
    """Resolve which dataset config YAML to use for a dataset.

    Resolution is intentionally simple and local:
    1. If ``explicit`` is provided, use that.
    2. Otherwise, always use ``<dataset_dir>/dataset.yaml``.

    This keeps a single canonical config per dataset and avoids
    confusion with older central-config layouts.
    """

    if explicit is not None:
        return explicit

    return dataset_dir / "dataset.yaml"


def validate_dataset_yaml(cfg: Dict[str, Any], path: Path) -> ValidationResult:
    """Validate the core structure of dataset.yaml.

    Checks:
    - top-level ``dataset`` block exists and has at least an ``id``.
    - ``sources`` is a list (for ingest).
    - ``tables`` is a mapping (for ingest/transform).
    """

    errors: List[str] = []
    warnings: List[str] = []

    if not cfg:
        errors.append(f"{path}: empty or not a mapping")
        return errors, warnings

    dataset = cfg.get("dataset")
    if not isinstance(dataset, dict):
        errors.append(f"{path}: missing or invalid 'dataset' section")
    else:
        if not dataset.get("id"):
            warnings.append(f"{path}: dataset.id missing; falling back to directory name")

    sources = cfg.get("sources")
    if sources is None:
        warnings.append(f"{path}: no 'sources' section; ingest may have nothing to read")
    elif not isinstance(sources, list):
        errors.append(f"{path}: 'sources' must be a list")

    tables = cfg.get("tables")
    if tables is None:
        warnings.append(f"{path}: no 'tables' section; ingest/transform may have nothing to write")
    elif not isinstance(tables, dict):
        errors.append(f"{path}: 'tables' must be a mapping of table name -> config")

    return errors, warnings


def validate_profile_yaml(cfg: Dict[str, Any], path: Path) -> ValidationResult:
    """Validate minimal structure of a dataset profile YAML.

    Checks:
    - profile has an id or name (optional but recommended).
    - defaults.standards is a mapping when present.
    """

    errors: List[str] = []
    warnings: List[str] = []

    if not cfg:
        warnings.append(f"{path}: empty profile; relying entirely on dataset.yaml")
        return errors, warnings

    defaults = cfg.get("defaults") or {}
    standards = defaults.get("standards") if isinstance(defaults, dict) else None
    if standards is not None and not isinstance(standards, dict):
        errors.append(f"{path}: defaults.standards must be a mapping when present")

    profile_id = cfg.get("profile_id") or cfg.get("id") or cfg.get("name")
    if not profile_id:
        warnings.append(f"{path}: profile missing 'profile_id'/'id'/'name'")

    return errors, warnings


def validate_mapping_yaml(cfg: Dict[str, Any], path: Path) -> ValidationResult:
    """Validate minimal structure of a tabular standard mapping YAML.

    Designed for DwC mappings but generic enough for other standards:
    - top-level ``tables`` should be a mapping from table file -> spec.
    """

    errors: List[str] = []
    warnings: List[str] = []

    if not cfg:
        errors.append(f"{path}: empty mapping file")
        return errors, warnings

    tables = cfg.get("tables")
    if tables is None:
        errors.append(f"{path}: missing top-level 'tables' block")
    elif not isinstance(tables, dict):
        errors.append(f"{path}: 'tables' must be a mapping of table_name -> config")

    return errors, warnings


def report_and_maybe_abort(errors: List[str], warnings: List[str], *, fatal: bool = True) -> None:
    """Print validation messages and optionally abort on errors.

    This is a convenience for CLI entrypoints. Library callers may
    prefer to inspect the errors/warnings directly.
    """

    for w in warnings:
        print("[config] WARNING:", w)
    if errors:
        for e in errors:
            print("[config] ERROR:", e)
        if fatal:
            raise SystemExit("Configuration validation failed; see errors above.")
