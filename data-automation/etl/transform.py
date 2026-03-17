
"""Generic transform script (staging -> processed).

This step applies dataset-declared derivations and light normalization
but stays *independent* of any particular standard (no DwC terms,
no ontology). All standard mapping is done later by export scripts.
"""

from pathlib import Path
import argparse
from typing import Dict, Any, List
import warnings
import pandas as pd
import yaml

from etl.helpers.config_validation import resolve_dataset_config_path, validate_dataset_yaml, report_and_maybe_abort


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def apply_derivations(df: pd.DataFrame, derivations: List[Dict[str, Any]]) -> pd.DataFrame:
    """Apply simple column-level derivations from dataset config.

    Rules are guarded so a shared list can be applied across tables
    without failing if some source columns are missing.
    """
    # Operate on a shallow copy to avoid surprising callers with in-place changes
    df = df.copy()

    for rule in derivations or []:
        op = rule.get("operation")
        tgt = rule.get("target")
        if not op or not tgt:
            continue

        if op == "divide":
            src = rule.get("source")
            value = rule.get("value")
            # Guard against non-numeric denominators (safe, skip invalid rules)
            if value is None:
                continue
            try:
                denom = float(value)
            except (TypeError, ValueError):
                continue
            if src in df.columns and denom != 0:
                df[tgt] = pd.to_numeric(df[src], errors="coerce") / denom

        elif op == "combine_datetime_flexible":
            # Accept either a strict two-name list, or a list of candidate lists
            # e.g. sources: [ ["date_local","date"], ["time_local","time"] ]
            sources_spec = rule.get("sources") or []

            def resolve_sources(spec, frame):
                # spec should be a list of 2 items; each item may be a string or list/tuple
                if not isinstance(spec, list) or len(spec) != 2:
                    return None
                resolved = []
                for item in spec:
                    # normalize to iterable of candidates
                    candidates = list(item) if isinstance(item, (list, tuple)) else [item]
                    found = None
                    for cand in candidates:
                        if isinstance(cand, str) and cand in frame.columns:
                            found = cand
                            break
                    if not found:
                        return None
                    resolved.append(found)
                return resolved

            # 1) direct exact-match pair
            date_col = time_col = None
            if isinstance(sources_spec, list) and len(sources_spec) == 2 and all(isinstance(s, str) and s in df.columns for s in sources_spec):
                date_col, time_col = sources_spec

            # 2) try resolving candidate lists
            if date_col is None:
                resolved = resolve_sources(sources_spec, df)
                if resolved:
                    date_col, time_col = resolved

            # 3) fallback to common conventional names if still unresolved
            if date_col is None:
                for cand_pair in [("date_local", "time_local"), ("date", "time")]:
                    if cand_pair[0] in df.columns and cand_pair[1] in df.columns:
                        date_col, time_col = cand_pair
                        break

            if not date_col or not time_col:
                # nothing we can do for this rule on this table
                continue

            dayfirst = bool(rule.get("dayfirst", False))
            assume_year = rule.get("assume_year")

            # Use pandas string dtype to handle missing values cleanly
            date_str = df[date_col].astype("string").str.strip().fillna("")
            # Optionally inject an assumed year when dates lack a year field
            if assume_year is not None:
                has_year = date_str.str.contains(r"\d{4}", regex=True, na=False)
                date_str = date_str.where(has_year, (date_str + f" {assume_year}").str.strip())

            time_str = df[time_col].astype("string").str.strip().fillna("")
            # Replace empty/NaT-like with midnight
            time_str = time_str.replace({"": "00:00:00", "NaT": "00:00:00"})

            combined = (date_str + " " + time_str).str.strip()
            # Pandas can emit a harmless warning when mixed date
            # formats are present (e.g. some values already in
            # ISO %Y-%m-%d while dayfirst=True). We silence that
            # specific warning only for this conversion.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Parsing dates in .* format when dayfirst=True was specified.",
                    category=UserWarning,
                )
                df[tgt] = pd.to_datetime(
                    combined,
                    errors="coerce",
                    dayfirst=dayfirst,
                )

        elif op == "copy":
            # Duplicate a column under a new name
            src = rule.get("source")
            if src in df.columns:
                df[tgt] = df[src].copy()

        elif op == "to_numeric":
            # Coerce a column to numeric (safe, errors->NaN)
            src = rule.get("source")
            if src in df.columns:
                df[tgt] = pd.to_numeric(df[src], errors="coerce")

        elif op == "strip":
            # Trim whitespace from string-like columns
            src = rule.get("source")
            if src in df.columns:
                # Preserve missing values (don't convert NA -> empty string)
                df[tgt] = df[src].astype("string").str.strip()

        elif op == "concat":
            # Concatenate multiple source columns into a single string
            sources = rule.get("sources") or []
            sep = rule.get("sep", "")
            if sources and all(s in df.columns for s in sources):
                # Build a temporary frame of string parts, replace missing with empty
                parts_df = pd.DataFrame({s: df[s].astype("string").fillna("") for s in sources})
                # Join only non-empty parts per row to avoid duplicate separators
                df[tgt] = (
                    parts_df.apply(lambda r: sep.join([x for x in r.tolist() if x]), axis=1).astype("string")
                )
    return df


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generic transform: staging -> processed Parquet")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        required=True,
        help="Path to the dataset directory (contains staging/, processed/, dataset.yaml)",
    )
    parser.add_argument("--staging", type=Path, default=None, help="Override staging directory (defaults to <dataset_dir>/staging)")
    parser.add_argument("--out", type=Path, default=None, help="Override processed directory (defaults to <dataset_dir>/processed)")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Dataset config YAML for derivations (defaults to <dataset_dir>/dataset.yaml)",
    )
    args = parser.parse_args(argv)

    dataset_dir = args.dataset_dir.resolve()
    staging_dir = args.staging or (dataset_dir / "staging")
    out_dir = args.out or (dataset_dir / "processed")
    cfg_path = resolve_dataset_config_path(dataset_dir, explicit=args.config)

    cfg = load_yaml(cfg_path)
    errors, cfg_warnings = validate_dataset_yaml(cfg, cfg_path)
    report_and_maybe_abort(errors, cfg_warnings, fatal=True)
    ensure_dir(out_dir)

    derivations: List[Dict[str, Any]] = cfg.get("derivations") or []

    summary: list[tuple[str, int, int]] = []

    for p in staging_dir.glob("*.parquet"):
        df = pd.read_parquet(p)
        before = len(df)
        df2 = apply_derivations(df, derivations)
        out_path = out_dir / p.name
        df2.to_parquet(out_path, index=False)
        summary.append((p.name, before, len(df2)))

    print("Transform complete. Processed tables:")
    for name, b, a in summary:
        print(f"  {name}: {b} -> {a} rows")


if __name__ == "__main__":
    main()

