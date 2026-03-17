"""Suggest a draft column-to-standard mapping for a dataset.

This is a lightweight CLI prototype intended for exploratory use: it
reads headers from the dataset `raw/` folder (CSV, Excel, Parquet),
matches them against a small set of known standard fields (Darwin Core
by default) using fuzzy matching, and writes a suggested YAML into
`mappings/<standard>_suggested.yaml` next to the dataset.
The output is intentionally a draft and must be reviewed by users
before being used by the pipeline.
"""
from __future__ import annotations
import difflib
try:
    from rapidfuzz import fuzz as rf_fuzz
except Exception:
    rf_fuzz = None
import re
from datetime import datetime
import hashlib
import statistics
from pathlib import Path
import argparse
import json
import logging
from typing import List, Dict, Any, Optional, Union
import pandas as pd
import yaml
from etl.helpers.cleaning import _clean_source_name

#common (dwc)standard Fields 
COMMON_DWC_FIELDS = [
    "eventID",
    "occurrenceID",
    "measurementID",
    "measurementType",
    "measurementValue",
    "measurementUnit",
    "measurementTypeID",
    "measurementUnitID",
    "decimalLatitude",
    "decimalLongitude",
    "eventDate",
    "eventTime",
    "scientificName",
    "vernacularName",
    "catalogNumber",
    "recordedBy",
    "locality",
    "locationID",
    # common free-text / remarks / categorical fields that improve suggestions
    "eventRemarks",
    "occurrenceRemarks",
    "habitat",
    "measurementRemarks",
]

# A small set of measurement hint words to help classify numeric columns
MEASURE_WORDS = ("dbh", "diameter", "height", "brows", "dung", "pellet", "cover", "count", "density", "percent", "pct", "temp", "temperature", "moisture", "elevation")

# Simple synonym hints to improve name matching in absence of a big term list
SYNONYMS = {
    "id": ["occurrenceID", "eventID"],
    "species": ["vernacularName", "scientificName"],
    "notes": ["eventRemarks", "occurrenceRemarks"],
    "note": ["eventRemarks", "occurrenceRemarks"],
    "date": ["eventDate"],
    "time": ["eventTime"],
    # combined datetime columns (e.g. datetime_local produced by derivations)
    "datetime": ["eventDate"],
}

# Column names that should always map to eventDate/eventTime regardless of other scoring
_DATETIME_COLS = {"date", "datetime_local", "datetime", "event_date", "eventdate"}
_TIME_COLS = {"time", "event_time", "eventtime"}


def _read_sample_table(dataset_dir: Path, max_rows: int = 200) -> (List[str], Dict[str, List[str]]):
    raw = dataset_dir / "raw"
    if not raw.exists():
        return [], {}

    # scan multiple common raw file types and aggregate headers/samples
    headers_seen: List[str] = []
    samples: Dict[str, List[str]] = {}
    for pat in ("*.csv", "*.xlsx", "*.parquet"):
        for p in sorted(raw.glob(pat)):
            try:
                if p.suffix.lower() == ".csv":
                    df = pd.read_csv(p, nrows=max_rows)
                elif p.suffix.lower() in (".xls", ".xlsx"):
                    df = pd.read_excel(p, nrows=max_rows)
                else:
                    # Parquet
                    df = pd.read_parquet(p)

                cols = [str(c) for c in df.columns]
                for c in cols:
                    if c not in headers_seen:
                        headers_seen.append(c)
                    try:
                        s = df[c].dropna().astype(str).head(5).tolist()
                    except Exception:
                        s = []
                    samples.setdefault(c, s)
            except Exception:
                # try next file
                continue

    return headers_seen, samples


def _normalize_name(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch.isspace())


_CAMEL_SPLIT = re.compile(r"(?<!^)(?=[A-Z])")

def _norm(s: str) -> str:
    """Normalize a header or term into a lowercase token string for comparison.

    - splits CamelCase
    - removes punctuation
    - collapses whitespace
    """
    if not s:
        return ""
    t = str(s)
    t = t.replace("_", " ").replace("-", " ").strip()
    t = _CAMEL_SPLIT.sub(" ", t)
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _score_name_match(source: str, target: str) -> float:
    """Return a 0..1 name-based similarity score using RapidFuzz when available,
    otherwise fall back to difflib.SequenceMatcher.
    """
    s = _norm(source or "")
    t = _norm(target or "")
    # prefer token-based ratios that ignore word order
    try:
        if rf_fuzz is not None:
            token_score = rf_fuzz.token_set_ratio(s, t) / 100.0
            partial = rf_fuzz.partial_ratio(s, t) / 100.0
            return max(token_score, partial)
    except Exception:
        pass

    # fallback to difflib on normalized tokens
    try:
        return difflib.SequenceMatcher(None, s, t).ratio()
    except Exception:
        return 0.0


def _numeric_ratio(vals: list) -> float:
    total = 0
    num = 0
    for v in vals:
        if v is None:
            continue
        vv = str(v).strip()
        if vv == "":
            continue
        total += 1
        try:
            float(vv)
            num += 1
        except Exception:
            pass
    return (num / total) if total else 0.0


def _parse_unit(header: str) -> str | None:
    # parse unit in parentheses e.g. "DBH (cm)" -> cm
    if not header:
        return None
    m = re.search(r"\(([^)]+)\)", header)
    if m:
        return m.group(1).strip()
    # some suffix patterns like _cm, _m, _pct
    suf = re.search(r"(_|\b)(cm|m|pct|%|percent|c|celsius|count|n)\b", header.lower())
    if suf:
        return suf.group(2)
    return None


def _is_latlon_header(h: str) -> bool:
    t = _norm(h)
    return any(x in t for x in ("lat", "latitude", "lon", "longitude", "easting", "northing", "utm"))


def _is_measurement_column(header: str, samples: list[str]) -> bool:
    h = _norm(header)
    # avoid treating lat/lon fields as measurement
    if _is_latlon_header(header):
        return False
    # if header contains measurement hint words or unit, prefer measurement
    if any(w in h for w in MEASURE_WORDS):
        return True
    if _parse_unit(header):
        return True
    # numeric ratio high and header hints numeric-ish
    nr = _numeric_ratio(samples)
    if nr >= 0.95:
        return True
    return False


def _load_standard_fields(dataset_dir: Path, standard: str) -> List[str]:
    """Try to load a canonical list of standard fields from project mappings.

    Looks for files in the project `mappings/` directory such as
    `<standard>_mapping.yaml` or `<standard>_fields.yaml`. If none found,
    falls back to built-in `COMMON_DWC_FIELDS`.
    """
    proj_mappings = dataset_dir.parent / "mappings"
    candidates = [
        proj_mappings / f"{standard}_fields.yaml",
        proj_mappings / f"{standard}_mapping.yaml",
        proj_mappings / f"{standard}.yaml",
    ]
    for p in candidates:
        if p.exists():
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                # If doc is a list, assume it's the fields list
                if isinstance(doc, list):
                    return [str(x) for x in doc]
                # Look for common keys
                for key in ("fields", "columns", "terms"):
                    if isinstance(doc.get(key), list):
                        return [str(x) for x in doc.get(key)]
                # Fallback: use top-level keys if mapping dict provided
                if isinstance(doc, dict) and doc:
                    return [str(k) for k in doc.keys()]
            except Exception:
                continue
    # fallback
    return COMMON_DWC_FIELDS


def _load_clean_columns(dataset_dir: Path, headers: List[str] | None = None) -> Dict[str, str]:
    """Load a clean-columns mapping if present and return original->clean mapping.

    Handles the nested structure written by ingest.py:
        meta: ...
        tables:
          oak_measurements:
            "DBH (cm)": dbh_cm
            ...

    Also handles flat dicts and lists for forward compatibility.
    """
    headers = headers or []
    cand_paths = [
        dataset_dir / "mappings" / "clean_columns.yaml",
        dataset_dir / "mappings" / "clean_columns.yml",
        dataset_dir.parent / "mappings" / "clean_columns.yaml",
        dataset_dir.parent / "mappings" / "clean_columns.yml",
    ]
    for p in cand_paths:
        if not p.exists():
            continue
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue

        mapping: Dict[str, str] = {}

        if isinstance(doc, dict):
            # ingest.py writes:  {meta: ..., tables: {table_name: {raw: clean, ...}, ...}}
            tables_block = doc.get("tables")
            if isinstance(tables_block, dict):
                for tbl_name, tbl_map in tables_block.items():
                    if isinstance(tbl_map, dict):
                        for k, v in tbl_map.items():
                            # raw header -> cleaned name; don't overwrite if already seen
                            mapping.setdefault(str(k), str(v))
                if mapping:
                    return mapping

            # flat dict: try to detect orientation using headers hint
            keys = {str(k) for k in doc.keys()}
            vals = {str(v) for v in doc.values() if isinstance(v, str)}
            if any(h in keys for h in headers):
                for k, v in doc.items():
                    if isinstance(v, str):
                        mapping[str(k)] = v
                return mapping
            if any(h in vals for h in headers):
                # inverted: clean->original
                for k, v in doc.items():
                    if isinstance(v, str):
                        mapping[str(v)] = str(k)
                return mapping
            # fallback: treat as original->clean
            for k, v in doc.items():
                if isinstance(v, str):
                    mapping[str(k)] = v
            if mapping:
                return mapping

        if isinstance(doc, list):
            for item in doc:
                if isinstance(item, dict):
                    for k, v in item.items():
                        mapping[str(k)] = str(v)
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    mapping[str(item[0])] = str(item[1])
            if mapping:
                return mapping

    return {}


def _apply_clean_map_to_suggestions(suggestions: List[Dict[str, Any]] | Dict[str, List[Dict[str, Any]]], clean_map: Dict[str, str]) -> None:
    """Mutate suggestions in-place to prefer cleaned column names.

    For any suggestion whose `source_column` matches a key in `clean_map`
    the function will set `original_source` to the original header and
    replace `source_column` with the cleaned name.
    """
    if not clean_map:
        return

    # clean_map is usually original_raw -> cleaned_name. Build both
    # orientations so we can apply the mapping whether suggestions
    # refer to raw headers (pre-ingest) or cleaned names (post-ingest).
    raw_to_clean: Dict[str, str] = {str(k): str(v) for k, v in clean_map.items()}
    clean_to_raw: Dict[str, str] = {str(v): str(k) for k, v in raw_to_clean.items()}

    def _apply_to_item(s: Dict[str, Any]) -> None:
        orig = s.get("source_column")
        if not orig:
            return
        # If suggestions reference the raw header, map to cleaned name.
        if orig in raw_to_clean:
            s["original_source"] = orig
            s["source_column"] = raw_to_clean[orig]
            return
        # If suggestions reference a cleaned name, attach the original raw header
        if orig in clean_to_raw:
            s["original_source"] = clean_to_raw[orig]
            # keep source_column as the cleaned name
            return

    if isinstance(suggestions, dict):
        for tbl, s_list in suggestions.items():
            for s in s_list:
                _apply_to_item(s)
    else:
        for s in suggestions:
            _apply_to_item(s)


def suggest_mapping(
    headers: List[str],
    samples: Dict[str, List[str]],
    standard: str = "dwc",
    target_fields: List[str] | None = None,
) -> List[Dict[str, Any]]:
    if target_fields is None:
        target_fields = COMMON_DWC_FIELDS
    suggestions: List[Dict[str, Any]] = []
    # confidence threshold: top candidate below this will not be auto-recommended
    RECOMMEND_THRESHOLD = 0.55

    def _samples_look_like_scientific(samp: List[str]) -> float:
        # quick heuristic: proportion of samples matching 'Genus species' pattern
        if not samp:
            return 0.0
        ok = 0
        tot = 0
        for v in samp:
            if not v:
                continue
            tot += 1
            if re.match(r"^[A-Z][a-z]+\s[a-z\-]+$", str(v).strip()):
                ok += 1
        return (ok / tot) if tot else 0.0

    for h in headers:
        # skip internal pipeline provenance columns added by ingest.py
        if h.startswith("_etl_"):
            continue
        # skip geometry-like columns (WKT produced by ingest for spatial sources)
        hl = h.lower()
        if hl in ("geometry", "geom", "wkt") or hl.endswith("_wkt") or "_geometry" in hl:
            continue

        samp = samples.get(h, [])
        nr = _numeric_ratio(samp)

        # Short-circuit: known datetime/time columns -> always map to eventDate/eventTime
        # This handles derived columns like datetime_local before the measurement classifier
        # would incorrectly claim them (they contain 'time' which is a MEASURE_WORD).
        h_lower = h.lower()
        if h_lower in _DATETIME_COLS:
            suggestions.append({
                "source_column": h,
                "kind": "field",
                "recommended": {"term": "eventDate"},
                "candidates": [{"term": "eventDate", "confidence": 0.95}],
                "confidence": 0.95,
                "confidence_breakdown": {"name": 0.95, "numeric": round(nr, 3)},
                "samples": samp,
                "canonical_table": "event",
                "notes": "Combined datetime column; mapped to eventDate.",
            })
            continue
        if h_lower in _TIME_COLS:
            suggestions.append({
                "source_column": h,
                "kind": "field",
                "recommended": {"term": "eventTime"},
                "candidates": [{"term": "eventTime", "confidence": 0.95}],
                "confidence": 0.95,
                "confidence_breakdown": {"name": 0.95, "numeric": round(nr, 3)},
                "samples": samp,
                "canonical_table": "event",
                "notes": "Time column; mapped to eventTime.",
            })
            continue

        # Measurement-like columns -> produce MeasurementOrFact recommendation
        if _is_measurement_column(h, samp):
            unit = _parse_unit(h)
            # human-friendly measurement type guessed from header (remove unit)
            mt = re.sub(r"\s*\([^)]*\)", "", str(h)).replace("_", " ").strip()
            mt = re.sub(r"\bnum\b|\bn\b", "count", mt, flags=re.I)
            measurement_type = mt or h
            confidence = max(0.6, min(0.99, nr + 0.2))
            suggestions.append(
                {
                    "source_column": h,
                    "kind": "measurement",
                    "recommended": {
                        "canonical_table": "measurement_or_fact",
                        "measurementType": measurement_type,
                        "measurementValue_from": h,
                        "measurementUnit": unit if unit else None,
                    },
                    "candidates": [],
                    "confidence": round(float(confidence), 3),
                    "confidence_breakdown": {"numeric": round(nr, 3)},
                    "samples": samp,
                    "notes": "Detected as measurement-like column; review unit and type.",
                }
            )
            continue

        # Non-measurement: compute name-based candidates
        name_scores: Dict[str, float] = {}
        for t in target_fields:
            name_scores[t] = _score_name_match(h, t)

        # add synonym hints: if header token matches a synonym key, give those terms a small bump
        hn = _norm(h)
        for key, terms in SYNONYMS.items():
            if key in hn:
                for term in terms:
                    name_scores[term] = max(name_scores.get(term, 0.0), 0.6)

        # sort top candidates
        ranked = sorted(name_scores.items(), key=lambda x: x[1], reverse=True)
        top_candidates = [ {"term": t, "confidence": round(float(s),3)} for t, s in ranked[:3] if s > 0.0 ]
        top_term, top_score = (ranked[0] if ranked else (None, 0.0))

        # species heuristic: prefer vernacularName if samples look non-scientific
        recommended_term = None
        notes = ""
        sci_prop = _samples_look_like_scientific(samp)
        if top_term in ("scientificName", "vernacularName"):
            # if samples look like binomials, prefer scientificName
            if sci_prop >= 0.5:
                recommended_term = "scientificName"
            else:
                recommended_term = "vernacularName"
        else:
            if top_score >= RECOMMEND_THRESHOLD:
                recommended_term = top_term

        # avoid numeric boost mapping numeric columns to lat/lon/time unless header matches lat/lon
        if nr >= 0.9 and not _is_latlon_header(h):
            # if the top candidate is lat/lon but header doesn't indicate it, drop as recommended
            if recommended_term in ("decimalLatitude", "decimalLongitude"):
                notes += "High numeric ratio; suspected measurement-like values — avoided mapping to lat/lon. "
                recommended_term = None

        kind = "field"
        if recommended_term in ("occurrenceID", "eventID", "measurementID"):
            kind = "id"
        if recommended_term in ("scientificName", "vernacularName"):
            kind = "name"
        if recommended_term in ("eventRemarks", "occurrenceRemarks", "measurementRemarks"):
            kind = "remarks"

        suggestions.append(
            {
                "source_column": h,
                "kind": kind,
                "recommended": ({"term": recommended_term} if recommended_term else {}),
                "candidates": top_candidates,
                "confidence": round(float(top_score), 3),
                "confidence_breakdown": {"name": round(float(top_score), 3), "numeric": round(nr, 3)},
                "samples": samp,
                "canonical_table": None,
                "notes": notes,
            }
        )

    return suggestions


def write_suggested_yaml(dataset_dir: Path, standard: str, suggestions: List[Dict[str, Any]]) -> Path:
    out_dir = dataset_dir / "mappings"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{standard}_suggested.yaml"
    out_path = out_dir / name
    meta = {"generated": datetime.now().astimezone().isoformat(), "standard": standard}
    # indicate whether the suggester used a clean-columns mapping
    def _cleaning_used(sugg: List[Dict[str, Any]] | Dict[str, List[Dict[str, Any]]]) -> bool:
        if isinstance(sugg, dict):
            for v in sugg.values():
                for s in v:
                    if s.get("original_source"):
                        return True
            return False
        for s in sugg:
            if s.get("original_source"):
                return True
        return False
    # suggestions may be a dict mapping table_key -> suggestions list, or a flat list
    if _cleaning_used(suggestions):
        meta["clean_columns_applied"] = True
        # If we applied a clean-columns mapping, the suggested mapping
        # refers to cleaned/canonical names — mark that explicitly.
        meta["column_schema"] = "canonical"

    if isinstance(suggestions, dict):
        payload = {"meta": meta, "tables": suggestions}
    else:
        payload = {"meta": meta, "suggestions": suggestions}
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out_path


def iter_input_tables(dataset_dir: Path) -> List[Path]:
    # Prefer staging/ (written by ingest.py) > processed/ > raw/
    staging = dataset_dir / "staging"
    if staging.exists():
        ps = sorted(staging.glob("*.parquet"))
        if ps:
            return ps

    processed = dataset_dir / "processed"
    if processed.exists():
        ps = sorted(processed.glob("*.parquet"))
        if ps:
            return ps

    raw = dataset_dir / "raw"
    if not raw.exists():
        return []
    files: List[Path] = []
    for pat in ("*.parquet", "*.csv", "*.xlsx", "*.xls"):
        files.extend(sorted(raw.glob(pat)))
    return files


def read_table(path: Path, max_rows: int = 200) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, nrows=max_rows)
    if path.suffix.lower() in (".xls", ".xlsx"):
        return pd.read_excel(path, nrows=max_rows)
    return pd.read_parquet(path)


def sample_values_df(df: pd.DataFrame, col: str, n: int = 10) -> List[str]:
    try:
        return df[col].dropna().astype(str).head(n).tolist()
    except Exception:
        return []





def convert_suggestions_to_standard(dataset_dir: Path, suggestions: Union[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]) -> Path:
    """Convert the flat suggestions list into a dwc_standard-style mapping per input table.

    Returns the written Path for the standard mapping file.
    """
    # support either a flat list of suggestions or a dict keyed by table -> suggestions
    per_table_lookup = None
    global_lookup: Dict[str, Dict[str, Any]] = {}
    if isinstance(suggestions, dict):
        per_table_lookup = {}
        for k, v in suggestions.items():
            pertab: Dict[str, Dict[str, Any]] = {}
            for s in v:
                key_clean = s.get("source_column")
                if key_clean:
                    pertab[key_clean] = s
                orig = s.get("original_source")
                if orig:
                    pertab[orig] = s
            per_table_lookup[k] = pertab
    else:
        for s in suggestions:
            key_clean = s.get("source_column")
            if key_clean:
                global_lookup[key_clean] = s
            orig = s.get("original_source")
            if orig:
                global_lookup[orig] = s
    # compute some lightweight metadata for traceability
    def _compute_clean_columns_hash() -> str | None:
        cand = dataset_dir / "mappings" / "clean_columns.yaml"
        if cand.exists():
            try:
                data = cand.read_bytes()
                return hashlib.sha256(data).hexdigest()
            except Exception:
                return None
        return None

    def _compute_confidence_summary() -> Dict[str, float]:
        vals: List[float] = []
        def _collect(sugg: Any) -> None:
            if isinstance(sugg, dict):
                for v in sugg.values():
                    for item in v:
                        c = item.get("confidence")
                        if isinstance(c, (int, float)):
                            vals.append(float(c))
            else:
                for item in sugg:
                    c = item.get("confidence")
                    if isinstance(c, (int, float)):
                        vals.append(float(c))

        _collect(suggestions)
        if not vals:
            return {"mean": 0.0, "count": 0}
        return {"mean": round(float(statistics.mean(vals)), 3), "count": len(vals)}

    out: Dict[str, Any] = {
        "meta": {
            "generated_by": "etl.helpers.suggest_mapping",
            "generated_at": datetime.now().astimezone().isoformat(),
            "standard": "Darwin Core",
            "version": "2023-10",
            "description": "Auto-generated DwC mapping (suggested). Human review required.",
            "column_schema": "canonical",
            "source_clean_columns_hash": _compute_clean_columns_hash(),
            "confidence_summary": _compute_confidence_summary(),
        },
        "ontology_annotations": {},
        "tables": {},
    }

    for p in iter_input_tables(dataset_dir):
        try:
            df = read_table(p, max_rows=200)
        except Exception:
            # skip unreadable table
            continue
        key = p.name if p.suffix.lower() == ".parquet" else f"{p.stem}.parquet"
        cols = [str(c) for c in df.columns]

        event: Dict[str, Any] = {}
        occurrence: Dict[str, Any] = {}
        measurements: List[Dict[str, Any]] = []

        # small heuristics for core columns
        def pick_id_column(cols: List[str]) -> Optional[str]:
            for c in cols:
                if c.lower() == "id":
                    return c
            for c in cols:
                cl = c.lower()
                if cl.endswith("id") or " id" in cl or "_id" in cl:
                    return c
            return None

        def pick_species_column(cols: List[str]) -> Optional[str]:
            for c in cols:
                cl = c.lower()
                if "species" in cl or "taxon" in cl or "scientific" in cl:
                    return c
            return None

        def pick_datetime_column(cols: List[str]) -> Optional[str]:
            for c in cols:
                cl = c.lower()
                if "date" in cl or "datetime" in cl or "time" in cl:
                    return c
            return None

        id_col = pick_id_column(cols)
        species_col = pick_species_column(cols)
        datetime_col = pick_datetime_column(cols)

        if id_col:
            cleaned = _clean_source_name(id_col)
            event["eventID"] = cleaned
            occurrence["occurrenceID"] = cleaned

        if species_col:
            occurrence["scientificName"] = _clean_source_name(species_col)
            occurrence["basisOfRecord"] = {"constant": "HumanObservation"}
            occurrence["occurrenceStatus"] = {"constant": "present"}

        if datetime_col:
            lc = datetime_col.lower()
            if "date" in lc or "datetime" in lc:
                event["eventDate"] = _clean_source_name(datetime_col)
            elif "time" in lc:
                event["eventTime"] = _clean_source_name(datetime_col)

        # pick the right lookup (per-table if available, otherwise global)
        if per_table_lookup is not None and key in per_table_lookup:
            lookup = per_table_lookup.get(key, {})
        else:
            lookup = global_lookup

        for c in cols:
            if c == id_col or c == species_col or c == datetime_col:
                continue
            s = lookup.get(c, {})
            src = _clean_source_name(c)
            # measurement suggestions
            if s.get("kind") == "measurement" or s.get("recommended", {}).get("canonical_table") == "measurement_or_fact":
                rec = s.get("recommended", {})
                # prefer suggester-provided values, else derive from header
                m_type = rec.get("measurementType") or re.sub(r"\s*\([^)]*\)", "", str(c)).strip()
                m_unit = rec.get("measurementUnit") or _parse_unit(c)
                m: Dict[str, Any] = {"source": src, "measurementType": m_type}
                if m_unit:
                    m["measurementUnit"] = m_unit
                # low-confidence note
                if s.get("confidence", 1.0) < 0.7:
                    m["measurementRemarks"] = "AUTO-SUGGESTED; review confidence"
                measurements.append(m)
                continue

            # direct DwC term mapping
            rec = s.get("recommended", {})
            term = rec.get("term")
            if term:
                if term in ("scientificName", "vernacularName", "individualCount", "basisOfRecord", "occurrenceStatus"):
                    occurrence[term] = src
                else:
                    event[term] = src
                continue

            # fallback heuristics: numeric -> measurement, else text measurement
            vals = sample_values_df(df, c, n=10)
            nr = _numeric_ratio(vals)
            if nr >= 0.6:
                measurements.append({"source": src, "measurementType": c, "measurementUnit": None})
            else:
                # preserve as measurement text to avoid losing columns
                measurements.append({"source": src, "measurementType": c, "measurementUnit": "text"})

        table_obj: Dict[str, Any] = {}
        if event:
            table_obj["event"] = event
        if occurrence:
            table_obj["occurrence"] = occurrence
        if measurements:
            table_obj["measurements"] = measurements

        out["tables"][key] = table_obj

    out_path = dataset_dir / "mappings" / "dwc_standard_suggested.yaml"
    out_path.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # also write a full report for UI/inspection
    report_path = dataset_dir / "mappings" / "dwc_suggested_report.yaml"
    report_payload = {"meta": {"generated": datetime.now().astimezone().isoformat()}, "suggestions": suggestions}
    report_path.write_text(yaml.safe_dump(report_payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out_path


def _load_profile_info(dataset_dir: Path) -> Dict[str, Any]:
    # Read dataset.yaml and profile if present to support canonical_table suggestions
    cfg_path = dataset_dir / "dataset.yaml"
    result: Dict[str, Any] = {}
    if not cfg_path.exists():
        return result
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return result

    d = cfg.get("dataset", {})
    profile_id = d.get("profile")
    result["dataset_id"] = d.get("id")
    result["profile_id"] = profile_id
    # load profile YAML from datasets root profiles dir
    if profile_id:
        profiles_dir = dataset_dir.parent / "profiles"
        profile_path = profiles_dir / f"{profile_id}.yaml"
        if profile_path.exists():
            try:
                result["profile"] = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            except Exception:
                result["profile"] = {}
    return result


def apply_profile_guidance(suggestions: List[Dict[str, Any]], profile_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Simple heuristics to pick canonical_table based on header names, sample types, and profile cores
    cores = []
    profile = profile_info.get("profile") or {}
    cores_cfg = profile.get("cores") or {}
    for k, v in (cores_cfg.items() if isinstance(cores_cfg, dict) else []):
        if isinstance(v, dict) and v.get("required"):
            cores.append(k)

    def guess_table_for_header(h: str, samples: List[str]) -> str:
        s = h.lower()
        # basic keyword heuristics
        if any(k in s for k in ("event", "date", "time", "lat", "lon", "location", "locality")):
            return "event"
        if any(k in s for k in ("species", "scientific", "vernacular", "taxon", "occurrence", "recordedby")):
            return "occurrence"
        # numeric-ish -> measurement
        numeric_count = 0
        for v in samples:
            try:
                float(v)
                numeric_count += 1
            except Exception:
                pass
        if numeric_count >= max(1, len(samples) // 2):
            return "measurement_or_fact"
        # fallback to measurement if 'measure' in header
        if "measure" in s or "value" in s or "unit" in s or "db" in s:
            return "measurement_or_fact"
        return "event"

    for m in suggestions:
        h = m.get("source_column", "")
        samp = m.get("samples") or []
        table = guess_table_for_header(h, samp)
        # prefer profile cores if guess maps to a non-required core, try to map names
        if table == "measurement_or_fact" and "measurement_or_fact" not in cores and cores:
            # if measurement core not required, still suggest measurement but mark note
            m["notes"] = m.get("notes", "") + "profile: measurement core not required; review. "
        m["canonical_table"] = table

    return suggestions


def main(argv: List[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    p = argparse.ArgumentParser(description="Suggest a draft mapping for a dataset (per-table)")
    p.add_argument("--dataset-dir", type=Path, required=True)
    p.add_argument("--standard", type=str, default="dwc", help="Target standard (dwc/darwin_core)")
    p.add_argument("--profile", type=str, default=None, help="Optional profile id to override dataset.yaml profile")
    p.add_argument("--standard-fields-file", type=Path, default=None, help="Optional path to a file listing standard fields (YAML/JSON) to use for suggestions")
    p.add_argument("--emit-standard", action="store_true", default=False, help="Also emit dwc_standard_suggested.yaml alongside the suggestions report")
    args = p.parse_args(argv)

    dataset_dir = args.dataset_dir

    # determine target standard fields (project mapping or supplied file)
    if args.standard_fields_file:
        try:
            sf = yaml.safe_load(args.standard_fields_file.read_text(encoding="utf-8")) or {}
            if isinstance(sf, list):
                target_fields = [str(x) for x in sf]
            elif isinstance(sf, dict) and sf.get("fields"):
                target_fields = [str(x) for x in sf.get("fields")]
            else:
                target_fields = _load_standard_fields(dataset_dir, args.standard)
        except Exception:
            target_fields = _load_standard_fields(dataset_dir, args.standard)
    else:
        target_fields = _load_standard_fields(dataset_dir, args.standard)

    # load profile info once
    profile_info = _load_profile_info(dataset_dir)
    if args.profile:
        if "/" in args.profile or args.profile.endswith(".yaml"):
            try:
                profile_path = Path(args.profile)
                if profile_path.exists():
                    profile_doc = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
                    profile_info["profile"] = profile_doc
                    profile_info["profile_id"] = profile_path.stem
            except Exception:
                pass
        else:
            profiles_dir = dataset_dir.parent / "profiles"
            profile_path = profiles_dir / f"{args.profile}.yaml"
            if profile_path.exists():
                try:
                    profile_doc = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
                    profile_info["profile"] = profile_doc
                    profile_info["profile_id"] = args.profile
                except Exception:
                    pass

    # per-table scoring (prefer processed/*.parquet)
    tables = iter_input_tables(dataset_dir)
    if not tables:
        logging.error("No input tables found in staging/, processed/, or raw/")
        return 2

    suggestions_by_table: Dict[str, List[Dict[str, Any]]] = {}
    all_headers: List[str] = []

    for p in tables:
        try:
            df = read_table(p, max_rows=200)
        except Exception:
            continue
        key = p.name if p.suffix.lower() == ".parquet" else f"{p.stem}.parquet"
        headers = [str(c) for c in df.columns]
        # accumulate headers to help detect clean_columns orientation
        for h in headers:
            if h not in all_headers:
                all_headers.append(h)

        samples: Dict[str, List[str]] = {}
        for c in headers:
            try:
                samples[c] = df[c].dropna().astype(str).head(5).tolist()
            except Exception:
                samples[c] = []

        table_suggestions = suggest_mapping(headers, samples, standard=args.standard, target_fields=target_fields)
        table_suggestions = apply_profile_guidance(table_suggestions, profile_info)
        suggestions_by_table[key] = table_suggestions

    # prefer cleaned names if dataset provides a clean_columns mapping
    clean_map = _load_clean_columns(dataset_dir, all_headers)
    if clean_map:
        _apply_clean_map_to_suggestions(suggestions_by_table, clean_map)
        logging.info("Applied clean-columns mapping for per-table suggestions")

    out = write_suggested_yaml(dataset_dir, args.standard, suggestions_by_table)
    logging.info("Wrote suggested mapping to %s", out)

    # optionally emit the standard-style draft
    if args.emit_standard:
        try:
            std_path = convert_suggestions_to_standard(dataset_dir, suggestions_by_table)
            logging.info("Wrote standard-style draft to %s", std_path)
        except Exception as e:
            logging.error("Failed to write standard-style draft: %s", e)

    # CLI preview
    previews = []
    for k, s in suggestions_by_table.items():
        if s:
            previews.append({"table": k, "sample": s[:3]})
    logging.info(json.dumps({"tables": len(suggestions_by_table), "preview": previews}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())