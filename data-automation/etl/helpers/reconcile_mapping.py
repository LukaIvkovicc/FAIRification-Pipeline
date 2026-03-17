"""Helpers to reconcile a mapping's source column names to actual processed column names.

This module provides a conservative, fuzzy-match based alignment used when
users keep a manual mapping that references older/raw column names but the
pipeline now applies automatic cleaning (so processed column names differ).

The strategy:
- For each table mapping, load the corresponding processed Parquet table
- For any mapping fields that reference a missing column, try to find the
  best-matching column from the processed table (optionally consult the
  dataset `mappings/clean_columns.yaml` for additional candidate names).
- Replace the mapping in-memory and return a reconciliation report.

This is intentionally permissive but conservative: matches below the
`threshold` are left unresolved and reported for manual review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import logging
import difflib
import yaml
import pandas as pd

logger = logging.getLogger(__name__)


def _load_clean_columns(clean_path: Path) -> Dict[str, Dict[str, str]]:
    if not clean_path or not clean_path.exists():
        return {}
    try:
        with open(clean_path, "r", encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
            return payload.get("tables", {}) if isinstance(payload, dict) else {}
    except Exception:
        logger.debug("Failed to read clean_columns at %s", clean_path)
        return {}


def _normalize(name: Optional[str]) -> str:
    if not name:
        return ""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _best_candidate(name: str, candidates: List[str], threshold: float) -> Optional[Tuple[str, float]]:
    if not candidates:
        return None
    name_n = _normalize(name)
    best = None
    best_score = 0.0
    for c in candidates:
        score = difflib.SequenceMatcher(None, name_n, _normalize(c)).ratio()
        if score > best_score:
            best_score = score
            best = c
    if best is not None and best_score >= threshold:
        return best, best_score
    return None


def reconcile_tables_cfg_with_processed(
    tables_cfg: Dict[str, Any],
    processed_dir: Path,
    clean_columns_path: Optional[Path] = None,
    threshold: float = 0.75,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (new_tables_cfg, report).

    - `tables_cfg` is the mapping's `tables` dict (loaded from YAML).
    - `processed_dir` is the dataset `processed/` directory to inspect.
    - `clean_columns_path` optionally points to `mappings/clean_columns.yaml`.
    - `threshold` is the minimum fuzzy-match ratio (0-1) to accept.
    """
    clean_tables = _load_clean_columns(Path(clean_columns_path)) if clean_columns_path else {}

    report: Dict[str, Any] = {"replacements": {}, "unresolved": {}}

    for table_key, table_map in list(tables_cfg.items()):
        # normalize key to filename
        if table_key.endswith(".parquet"):
            table_filename = table_key
        else:
            table_filename = f"{table_key}.parquet"

        src_path = processed_dir / table_filename
        if not src_path.exists():
            # try the provided key as-is
            alt = processed_dir / table_key
            if alt.exists():
                src_path = alt
            else:
                logger.info("[reconcile] processed table not found, skipping: %s", table_filename)
                continue

        try:
            df = pd.read_parquet(src_path)
        except Exception:
            logger.debug("Failed to read processed table %s, skipping", src_path)
            continue

        cols = [str(c) for c in df.columns]

        table_replacements: List[Tuple[str, str, float]] = []
        table_unresolved: List[str] = []

        # helper to attempt to reconcile a single name and update container
        def _reconcile_name(name: str) -> Optional[str]:
            if not name or name in cols:
                return name

            # candidate pool: processed columns
            candidates = list(cols)

            # include clean_columns raw names and their cleaned targets for this table
            clean_map = clean_tables.get(table_key) or clean_tables.get(table_filename) or {}
            for raw, clean in clean_map.items():
                if raw not in candidates:
                    candidates.append(raw)
                if clean not in candidates:
                    candidates.append(clean)

            # fuzzy-match
            best = _best_candidate(name, candidates, threshold)
            if best:
                match, score = best
                # If match is a raw header that isn't an actual processed column, prefer the cleaned name
                if match in clean_map:
                    cleaned = clean_map.get(match)
                    if cleaned in cols:
                        return cleaned
                # otherwise if match is present in processed columns, return it
                if match in cols:
                    return match
                # otherwise if match looks like a cleaned name in the clean_map values, return that
                for r, c in clean_map.items():
                    if c == match and c in cols:
                        return c
                # fallback: return match (even if not in cols) — caller will treat as unresolved
                return match
            return None

        # check event and occurrence fields
        event_spec = table_map.get("event") or {}
        if isinstance(event_spec, dict):
            # eventID can be a string column name
            e_id = event_spec.get("eventID")
            if isinstance(e_id, str) and e_id not in cols:
                new = _reconcile_name(e_id)
                if new and new in cols:
                    event_spec["eventID"] = new
                    table_replacements.append((e_id, new, 1.0))
                else:
                    table_unresolved.append(e_id)

        occ_spec = table_map.get("occurrence") or {}
        if isinstance(occ_spec, dict):
            for key, val in occ_spec.items():
                if key == "prefix":
                    continue
                if isinstance(val, str) and val not in cols:
                    new = _reconcile_name(val)
                    if new and new in cols:
                        occ_spec[key] = new
                        table_replacements.append((val, new, 1.0))
                    else:
                        table_unresolved.append(val)

        # measurements
        for m in table_map.get("measurements", []) or []:
            if not isinstance(m, dict):
                continue
            src = m.get("source")
            if src and isinstance(src, str) and src not in cols:
                new = _reconcile_name(src)
                if new and new in cols:
                    m["source"] = new
                    table_replacements.append((src, new, 1.0))
                else:
                    table_unresolved.append(src)

        if table_replacements:
            report["replacements"][table_filename] = [
                {"from": a, "to": b, "score": s} for (a, b, s) in table_replacements
            ]
        if table_unresolved:
            report["unresolved"][table_filename] = sorted(list(set(table_unresolved)))

        # store updated mapping back
        tables_cfg[table_key] = table_map

    return tables_cfg, report
