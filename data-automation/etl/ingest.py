"""
Generic ingest script.
Reads raw data sources described in dataset.yaml
and writes staging parquet tables.

NO semantic logic allowed here.
"""

from pathlib import Path
import argparse
from typing import Optional, Set
import logging
import pandas as pd
import yaml
from etl.helpers.config_validation import (
    validate_dataset_yaml,
    report_and_maybe_abort,
    resolve_dataset_config_path,
)
from datetime import datetime, timezone
from etl.helpers.cleaning import build_final_rename_map

logger = logging.getLogger(__name__)

# -------------------------
# Core utilities
# -------------------------

def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

# -------------------------
# Ingest logic
# -------------------------

def read_source(
    source_cfg: dict,
    dataset_dir: Path,
    sheet_names: Optional[Set[str]] = None,
) -> dict[str, pd.DataFrame] | pd.DataFrame:
    """
    Read a raw source and return named tables.
    """
    src_type = source_cfg["type"]
    raw_path = Path(source_cfg["path"])
    # Resolve relative to dataset directory so configs are portable
    path = raw_path if raw_path.is_absolute() else (dataset_dir / raw_path)

    # Tabular formats
    if src_type == "excel":
        try:
            xls = pd.ExcelFile(path)
        except Exception as exc:
            raise SystemExit(f"Failed to open Excel file {path}: {exc}") from exc

        # If the dataset config declared specific sheets for this source,
        # only read those sheets to avoid loading large unrelated sheets.
        if sheet_names:
            sheets = [s for s in xls.sheet_names if str(s) in sheet_names]
        else:
            sheets = list(xls.sheet_names)

        result = {}
        for sheet in sheets:
            try:
                # Use the already-opened ExcelFile for better performance
                result[str(sheet)] = xls.parse(sheet_name=sheet)
            except Exception as exc:  # pragma: no cover - IO
                raise SystemExit(f"Failed to read sheet '{sheet}' from {path}: {exc}") from exc
        logger.info("[ingest] Excel source %s: loaded sheets=%s", path, list(result.keys()))
        return result

    if src_type == "csv":
        # Single-table source: return DataFrame directly
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            raise SystemExit(f"Failed to read CSV {path}: {exc}") from exc
        logger.info("[ingest] CSV source %s: rows=%s cols=%s", path, len(df), len(df.columns))
        return df

    if src_type == "tsv":
        try:
            df = pd.read_csv(path, sep="\t")
        except Exception as exc:
            raise SystemExit(f"Failed to read TSV {path}: {exc}") from exc
        logger.info("[ingest] TSV source %s: rows=%s cols=%s", path, len(df), len(df.columns))
        return df

    if src_type == "parquet":
        try:
            df = pd.read_parquet(path)
        except Exception as exc:
            raise SystemExit(f"Failed to read Parquet {path}: {exc}") from exc
        logger.info("[ingest] Parquet source %s: rows=%s cols=%s", path, len(df), len(df.columns))
        return df

    # Columnar/array formats commonly used in hydrology / satellite / climate
    if src_type == "netcdf":
        try:
            import xarray as xr  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SystemExit(
                "Source type 'netcdf' requires xarray. Install it in the ETL environment "
                "(e.g. pip install xarray)."
            ) from exc

        ds = xr.open_dataset(path)
        # Simple, generic conversion: full multi-indexed dataframe
        return ds.to_dataframe().reset_index()

    # Vector spatial data (shapefiles, GeoPackage, etc.)
    if src_type in {"shapefile", "vector"}:
        try:
            import geopandas as gpd  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SystemExit(
                "Source type 'shapefile'/'vector' requires geopandas. Install it in the ETL environment "
                "(e.g. pip install geopandas)."
            ) from exc

        gdf = gpd.read_file(path)
        # Convert geometry column to WKT strings to avoid parquet/pyarrow issues.
        if "geometry" in gdf.columns:
            geom_col = gdf.geometry.name
            try:
                gdf[geom_col] = gdf[geom_col].apply(lambda g: g.wkt if g is not None else None)
            except Exception:
                gdf[geom_col] = gdf[geom_col].apply(lambda g: str(g) if g is not None else None)
        logger.info("[ingest] Vector source %s: rows=%s cols=%s", path, len(gdf), len(gdf.columns))
        return pd.DataFrame(gdf)

    # more source types can be added here as new domains/formats appear

    supported = ["excel", "csv", "tsv", "parquet", "netcdf", "shapefile", "vector"]
    raise ValueError(f"Unsupported source type: {src_type}. Supported types: {supported}")

def ingest_table(table_cfg: dict, sources: dict, cleaning_cfg: dict) -> tuple[pd.DataFrame, dict]:
    """
    Apply table-level ingest rules:
    - select source
    - select sheet
    - rename columns
    """
    source_id = table_cfg["source"]
    sheet = table_cfg.get("sheet")

    if source_id not in sources:
        raise SystemExit(f"Unknown source id '{source_id}' in table '{table_cfg.get('name', '<unnamed>')}'. Available sources: {list(sources.keys())}")

    src = sources[source_id]
    if isinstance(src, dict):
        if sheet is None:
            raise ValueError(f"Table '{table_cfg['name']}' requires 'sheet' for multi-table source '{source_id}'")
        if sheet not in src:
            raise SystemExit(
                f"Sheet '{sheet}' not found in source '{source_id}'. Available sheets: {list(src.keys())}"
            )
        df = src[sheet].copy()
    else:
        df = src.copy()

    # capture raw header names (before any renaming)
    raw_cols = [str(c) for c in df.columns]

    # cleaning settings
    cleaning_enabled = bool(cleaning_cfg.get("enabled", True))
    cleaning_method = str(cleaning_cfg.get("method", "builtin"))

    manual = table_cfg.get("rename", {}) or {}
    # warn if user provided manual rename keys that do not exist in raw columns
    try:
        manual_keys = {str(k) for k in manual.keys()}
    except Exception:
        manual_keys = set()
    missing_manual = manual_keys - set(raw_cols)
    if missing_manual:
        logger.warning(
            "Manual rename keys %s not found in raw columns for table '%s'. Available raw columns: %s",
            sorted(list(missing_manual)),
            table_cfg.get("name", "<unnamed>"),
            raw_cols,
        )

    # build final rename map (raw -> cleaned)
    final_map = build_final_rename_map(raw_cols, manual, cleaning_enabled, cleaning_method)

    # apply final map to dataframe
    df = df.rename(columns=final_map)

    # warn if primary key (if provided) is not present after renaming
    pk = table_cfg.get("primary_key")
    if pk and str(pk) not in df.columns:
        logger.warning(
            "Primary key '%s' not found in final columns for table '%s'. Available columns: %s",
            pk,
            table_cfg.get("name", "<unnamed>"),
            list(df.columns),
        )

    # Optionally drop any columns that are not explicitly mapped in the
    # rename block. Interpreted AFTER renaming so we operate on final names.
    drop_unmapped = bool(table_cfg.get("drop_unmapped_columns"))
    if drop_unmapped:
        pk = table_cfg.get("primary_key")
        # If user provided explicit keep_columns, prefer that
        keep_cols = table_cfg.get("keep_columns")
        if isinstance(keep_cols, list) and keep_cols:
            allowed = {str(c) for c in keep_cols}
        elif manual:
            # keep only user-provided manual targets
            allowed = {final_map[k] for k in manual.keys() if k in final_map}
        else:
            allowed = None

        if allowed is not None:
            if pk:
                allowed.add(str(pk))
            cols_to_keep = [c for c in df.columns if c in allowed]
            if cols_to_keep:
                df = df.loc[:, cols_to_keep]

    # Optionally allow datasets to restrict which columns are carried
    # forward from the raw source via an explicit whitelist. This is
    # interpreted after renaming (and after drop_unmapped, if used).
    keep_cols = table_cfg.get("keep_columns")
    if isinstance(keep_cols, list) and keep_cols:
        keep_set = {str(c) for c in keep_cols}
        cols_to_keep = [c for c in df.columns if c in keep_set]
        if cols_to_keep:
            df = df.loc[:, cols_to_keep]

    # enforce unique column names by keeping the first occurrence
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

    # attach provenance
    df["_etl_source_table"] = table_cfg["name"]
    df["_etl_source_id"] = source_id

    # Normalise object-typed columns to pandas string dtype so that
    # pyarrow/parquet doesn't choke on mixed numeric/text columns.
    for col, dt in df.dtypes.items():
        if pd.api.types.is_object_dtype(dt):
            if df[col].apply(lambda x: isinstance(x, (bytes, bytearray))).any():
                df[col] = df[col].apply(
                    lambda b: b.decode("utf-8") if isinstance(b, (bytes, bytearray)) else b
                )
            df[col] = df[col].astype("string")
    # determine which mappings survived (only include columns that remain)
    kept = set(str(c) for c in df.columns)
    used_map = {raw: new for raw, new in final_map.items() if new in kept}

    return df, used_map

# -------------------------
# Main
# -------------------------

def main(argv: list[str] | None = None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Generic ingest: raw -> staging Parquet")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        required=True,
        help="Path to the dataset directory (must contain dataset.yaml)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional explicit dataset config YAML; defaults to <dataset_dir>/dataset.yaml",
    )
    args = parser.parse_args(argv)

    dataset_dir = args.dataset_dir.resolve()
    cfg_path = resolve_dataset_config_path(dataset_dir, explicit=args.config)
    if not cfg_path.exists():
        raise SystemExit(f"Dataset config not found: {cfg_path}")

    cfg = load_yaml(cfg_path)

    # Basic config validation so ingest fails fast with clear messages.
    errors, warnings = validate_dataset_yaml(cfg, cfg_path)
    report_and_maybe_abort(errors, warnings, fatal=True)

    staging_dir = dataset_dir / "staging"
    ensure_dir(staging_dir)

    # Determine which Excel sheets are actually referenced by tables
    # so we avoid reading every sheet unnecessarily.
    sheet_map: dict[str, set[str]] = {}
    for name, table_cfg in (cfg.get("tables") or {}).items():
        src_id = table_cfg.get("source")
        sheet = table_cfg.get("sheet")
        if src_id and sheet:
            s = sheet_map.get(src_id)
            if s is None:
                s = set()
                sheet_map[src_id] = s
            s.add(str(sheet))

    # read sources (pass sheet sets when applicable)
    sources = {}
    for src in cfg["sources"]:
        src_id = src["id"]
        sheet_names = sheet_map.get(src_id)
        sources[src_id] = read_source(src, dataset_dir, sheet_names)

    # ingest tables and build clean-columns mapping
    clean_mappings: dict = {}

    # cleaning configuration (defaults)
    cleaning_cfg = cfg.get("cleaning", {})
    cleaning_enabled = cleaning_cfg.get("enabled", True)
    cleaning_method = cleaning_cfg.get("method", "builtin")
    write_mapping = cleaning_cfg.get("write_mapping", True)

    for name, table_cfg in cfg["tables"].items():
        table_cfg["name"] = name
        df, used_map = ingest_table(table_cfg, sources, cleaning_cfg)

        # write staging parquet (prefer pyarrow + snappy, fallback to default)
        out_path = staging_dir / f"{name}.parquet"
        try:
            df.to_parquet(out_path, index=False, engine="pyarrow", compression="snappy")
        except Exception as exc:
            logger.warning("Failed to write parquet with pyarrow/snappy for %s: %s; retrying default writer", out_path, exc)
            try:
                df.to_parquet(out_path, index=False)
            except Exception as exc2:
                raise SystemExit(f"Failed to write Parquet for table {name} at {out_path}: {exc2}") from exc2
        logger.info("[ingest] Ingested %s: %d rows", name, len(df))

        if used_map:
            clean_mappings[name] = used_map

    # persist mappings/clean_columns.yaml if requested
    if write_mapping and clean_mappings:
        mappings_dir = dataset_dir / "mappings"
        ensure_dir(mappings_dir)
        out_path = mappings_dir / "clean_columns.yaml"
        meta = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "etl.ingest",
            "method": cleaning_method,
        }
        payload = {"meta": meta, "tables": clean_mappings}
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        logger.info("[ingest] Wrote clean-columns mapping to %s", out_path)

if __name__ == "__main__":
    main()
