"""Column cleaning utilities for the FAIRification(ETL) pipeline.

Provides deterministic builtin cleaning and an optional pyjanitor-backed
mode. These helpers are intentionally small and dependency-light so the
pipeline can run without pyjanitor installed.
"""
from __future__ import annotations
from typing import List, Dict, Optional, Any
import re
import importlib.util


def _parse_unit(header: str) -> Optional[str]:
    if not header:
        return None
    m = re.search(r"\(([^)]+)\)", header)
    if m:
        return m.group(1).strip()
    suf = re.search(r"(_|\b)(cm|m|pct|%|percent|c|celsius|count|n)\b", header.lower())
    if suf:
        return suf.group(2)
    return None


def _normalize_unit(unit_raw: Optional[str]) -> Optional[str]:
    if not unit_raw:
        return None
    u = str(unit_raw).lower().strip()
    if "%" in u or "percent" in u or u == "pct":
        return "pct"
    # remove degree symbols
    u = u.replace("˚", "").replace("°", "").replace("º", "")
    # normalize separators to underscores and remove unsafe chars
    u = re.sub(r"[^a-z0-9]+", "_", u)
    u = u.strip("_")
    return u or None


def _clean_source_name(col: str) -> str:
    s = (col or "").strip()
    is_count = False
    if s.startswith("#"):
        is_count = True
        s = s.lstrip("#").strip()
    s = s.replace("|", " ")
    unit = _parse_unit(col)
    s = s.lower()
    s = s.replace("/", " ")
    # Strip the unit parenthetical BEFORE general cleaning so it doesn't
    # get baked into the base name and then appended again as a suffix.
    if unit:
        s = re.sub(r"\([^)]*\)", " ", s)
    else:
        s = re.sub(r"[()]+", " ", s)
    s = re.sub(r"[^a-z0-9\s\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("-", "_")
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("_")
    if unit:
        u = _normalize_unit(unit)
        if u and u not in s.split("_"):
            s = f"{s}_{u}"
    if is_count and not s.endswith("_n"):
        s = f"{s}_n"
    return s


def _pyjanitor_postprocess(original: str, pj_name: str) -> str:
    """Post-process a pyjanitor-cleaned name to preserve units / count / range hints.

    Strategy:
    - For headers containing special characters (% > < | #) prefer the builtin cleaner.
    - Otherwise prefer the pyjanitor base but append normalized unit or count suffix
    if the builtin result indicates those and they are missing from the pyjanitor name.
    """
    # if original contains special tokens, prefer builtin deterministic result
    if any(ch in (original or "") for ch in ("%", ">", "<", "|", "#")):
        return _clean_source_name(original)

    builtin = _clean_source_name(original)
    final = pj_name or ""

    # ensure count suffix
    if builtin.endswith("_n") and not final.endswith("_n"):
        final = f"{final}_n"

    # ensure normalized unit suffix if builtin has one
    unit_raw = _parse_unit(original)
    if unit_raw:
        unit_norm = _normalize_unit(unit_raw)
        if unit_norm and unit_norm not in final.split("_"):
            final = f"{final}_{unit_norm}"

    # handle > / < by prefixing numeric token with gt/lt when possible
    if ">" in (original or "") and "gt" not in final:
        toks = final.split("_")
        for i, t in enumerate(toks):
            if re.search(r"\d", t):
                toks[i] = f"gt{t}" if not t.startswith("gt") else t
                final = "_".join(toks)
                break
        else:
            final = f"{final}_gt"

    if "<" in (original or "") and "lt" not in final:
        toks = final.split("_")
        for i, t in enumerate(toks):
            if re.search(r"\d", t):
                toks[i] = f"lt{t}" if not t.startswith("lt") else t
                final = "_".join(toks)
                break
        else:
            final = f"{final}_lt"

    final = re.sub(r"__+", "__", final).strip("_")
    return final


def _auto_clean_map(raw_cols: List[str], method: str) -> Dict[str, str]:
    """Return a mapping raw -> cleaned names using chosen method.

    If `method` is 'pyjanitor' and pyjanitor is available, use it; otherwise
    fall back to the builtin cleaner.
    """
    if method != "pyjanitor":
        return {c: _clean_source_name(c) for c in raw_cols}

    # pyjanitor optional path: try to clean all columns in one go
    if importlib.util.find_spec("janitor") is None:
        return {c: _clean_source_name(c) for c in raw_cols}

    try:
        import pandas as _pd
        import janitor  # type: ignore
        tmp = _pd.DataFrame(columns=raw_cols)
        out = tmp.clean_names()
        pj_map = dict(zip(raw_cols, [str(x) for x in out.columns]))
        # post-process pyjanitor results to preserve units/counts/range hints
        final: Dict[str, str] = {}
        for orig in raw_cols:
            pj_name = pj_map.get(orig, _clean_source_name(orig))
            # for headers with explicit special tokens prefer builtin
            if any(ch in (orig or "") for ch in ("%", ">", "<", "|", "#")):
                final[orig] = _clean_source_name(orig)
            else:
                final[orig] = _pyjanitor_postprocess(orig, pj_name)
        return final
    except Exception:
        return {c: _clean_source_name(c) for c in raw_cols}


def _ensure_unique(values_in_order: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for v in values_in_order:
        if v not in seen:
            seen[v] = 1
            out.append(v)
        else:
            seen[v] += 1
            out.append(f"{v}__{seen[v]}")
    return out


def build_final_rename_map(
    raw_cols: List[str],
    manual_overrides: Dict[str, Any],
    cleaning_enabled: bool,
    cleaning_method: str,
) -> Dict[str, str]:
    """Build a deterministic final rename map (raw_header -> cleaned_name).

    - If cleaning is disabled, identity is used.
    - Manual overrides (keys are raw headers) win over auto-cleaned names.
    - Uniqueness is enforced by appending __{n} for collisions.
    """
    if cleaning_enabled:
        auto = _auto_clean_map(raw_cols, cleaning_method)
    else:
        auto = {c: str(c) for c in raw_cols}

    final_in_order: List[str] = []
    for c in raw_cols:
        if c in manual_overrides:
            final_in_order.append(str(manual_overrides[c]))
        else:
            final_in_order.append(str(auto.get(c, c)))

    final_unique = _ensure_unique(final_in_order)
    return {raw: final for raw, final in zip(raw_cols, final_unique)}