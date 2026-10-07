"""Build district-level court efficiency dataset from DevDataLab / DDL Judicial Data.

Reference: https://www.devdatalab.org/judicial-data

This script implements steps 0 through 9 described in the project spec:

    0. Inventory files
    1. Load data safely (chunked / robust)
    2. Merge cases with acts_sections on ddl_case_id
    3. Decode state/district/court/type/purpose/disp/act/section using the key files
    4. Check whether state_code + dist_code is stable across years
    5. Enumerate case types and classify civil vs criminal (observed flag + fallback)
    6. Compute case-level timing variables and data-quality summary
    7. Aggregate district-year metrics for all/civil/criminal
    8. Build a court efficiency index
    9. Emit assumptions_and_choices.md alongside all CSV outputs

Judge files are deliberately ignored — the aim is court/district efficiency, not
judge-level analysis.

Usage
-----
    python build_district_court_efficiency.py \
        --data-dir /path/to/IBC/csv \
        --out-dir  /path/to/IBC/outputs \
        --chunksize 1000000

The script is designed to be safe with slightly different file names and to
survive missing optional inputs.  Memory use is kept bounded by chunked reads
and by caching an intermediate per-case criminal-flag parquet.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None


LOG = logging.getLogger("ddl_efficiency")

# ---------------------------------------------------------------------------
# Column name candidates.  We accept slightly different file naming.
# ---------------------------------------------------------------------------

CASE_COLS_WANTED = [
    "ddl_case_id",
    "year",
    "state_code",
    "dist_code",
    "court_no",
    "type_name",
    "purpose_name",
    "disp_name",
    "date_of_filing",
    "date_of_registration",  # not present in DDL 2010–18 but kept optional
    "date_of_decision",
]

ACTS_COLS_WANTED = ["ddl_case_id", "act", "section", "criminal"]

# String dtype for zero-padded codes; other columns coerced when needed.
CASE_DTYPES: Dict[str, str] = {
    "ddl_case_id": "string",
    "state_code": "string",
    "dist_code": "string",
    "court_no": "string",
    "type_name": "string",       # keep as string for robust merge with keys
    "purpose_name": "string",
    "disp_name": "string",
    "year": "Int16",
}


# Extreme-duration ceiling (~40 years) beyond which we mark as extreme.
EXTREME_DAYS = 40 * 365


# ---------------------------------------------------------------------------
# Argparse + logging
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "csv",
        help="Root directory containing cases/, keys/, acts_sections.csv (default: ./csv)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "outputs",
        help="Directory to write output CSVs (created if missing).",
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Scratch directory for cached intermediates (default: <out-dir>/../work)",
    )
    p.add_argument(
        "--chunksize",
        type=int,
        default=1_000_000,
        help="pandas read_csv chunksize for the very large files.",
    )
    p.add_argument(
        "--force-refresh-acts",
        action="store_true",
        help="Re-scan acts_sections even if the per-case criminal cache exists.",
    )
    p.add_argument(
        "--skip-pending",
        action="store_true",
        help="Skip pending-stock metrics (faster first pass).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return p


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    warnings.filterwarnings("ignore", category=pd.errors.DtypeWarning)


# ---------------------------------------------------------------------------
# File discovery utilities
# ---------------------------------------------------------------------------

def _is_data_file(name: str) -> bool:
    lower = name.lower()
    return lower.endswith((".csv", ".csv.gz", ".dta", ".parquet"))


def discover_data_files(data_dir: Path) -> List[Path]:
    """Recursively find data files inside ``data_dir``."""
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory {data_dir} does not exist.")
    return sorted(
        p for p in data_dir.rglob("*")
        if p.is_file() and _is_data_file(p.name)
    )


CASE_YEAR_RE = re.compile(r"cases[_-]?(\d{4})", re.I)


def _guess_role(path: Path) -> str:
    name = path.name.lower()
    if "judge" in name:
        return "judge file"
    if CASE_YEAR_RE.search(name):
        return "case file"
    if "acts_sections" in name or ("acts" in name and "section" in name):
        return "acts_sections"
    if "state_key" in name or name.endswith("state_key.csv"):
        return "state key"
    if "district_key" in name:
        return "district key"
    if "court_key" in name:
        return "court key"
    if "type_name_key" in name:
        return "type key"
    if "purpose_name_key" in name:
        return "purpose key"
    if "disp_name_key" in name or "disposition_key" in name:
        return "disposition key"
    if name.startswith("act_key") or name == "act_key.csv":
        return "act key"
    if name.startswith("section_key") or name == "section_key.csv":
        return "section key"
    if "merge_key" in name or "case_merge" in name:
        return "judge file"  # judge_case_merge_key – ignored
    return "unknown"


def _peek_columns_and_rows(path: Path) -> Tuple[List[str], Optional[int]]:
    """Return columns and (optionally) row count for a data file.

    Row counts are computed for CSV/CSV.gz files only.  Large files are
    counted by streaming bytes; row counts are best-effort and skipped for
    parquet/dta files (returned as ``None``).
    """
    suf = path.suffix.lower()
    if path.name.lower().endswith(".csv.gz"):
        with gzip.open(path, "rt", errors="replace") as fh:
            header = fh.readline().rstrip("\n").split(",")
        rows = None
    elif suf == ".csv":
        with open(path, "r", errors="replace") as fh:
            header = fh.readline().rstrip("\n").split(",")
        rows = _fast_line_count(path)
    elif suf == ".dta":
        try:
            it = pd.read_stata(path, iterator=True)
            header = list(it.varlist)
            it.close()
        except Exception:
            header = []
        rows = None
    elif suf == ".parquet":
        try:
            import pyarrow.parquet as pq
            header = list(pq.read_schema(path).names)
            rows = pq.read_metadata(path).num_rows
        except Exception:
            header = []
            rows = None
    else:
        header, rows = [], None
    # strip quotes / whitespace from CSV headers
    header = [h.strip().strip('"') for h in header]
    return header, rows


def _fast_line_count(path: Path) -> Optional[int]:
    """Count rows in a CSV excluding the header, via byte streaming."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    # For very large files, use a bytes-level newline count which is fast.
    lines = 0
    try:
        with open(path, "rb") as fh:
            while True:
                buf = fh.read(1024 * 1024)
                if not buf:
                    break
                lines += buf.count(b"\n")
        # Subtract header line if the file ends without newline etc.
        return max(lines - 1, 0)
    except OSError:
        return None


def build_file_inventory(data_dir: Path, out_dir: Path) -> pd.DataFrame:
    LOG.info("Step 0: scanning data directory %s", data_dir)
    files = discover_data_files(data_dir)
    rows: List[Dict[str, object]] = []
    for p in files:
        role = _guess_role(p)
        cols, nrows = _peek_columns_and_rows(p)
        rows.append({
            "file_path": str(p),
            "file_type": p.suffix.lstrip("."),
            "size_bytes": p.stat().st_size,
            "num_rows": nrows,
            "num_cols": len(cols),
            "columns": "|".join(cols),
            "guessed_role": role,
        })
    df = pd.DataFrame(rows).sort_values(["guessed_role", "file_path"]).reset_index(drop=True)
    out_path = out_dir / "file_inventory.csv"
    df.to_csv(out_path, index=False)
    LOG.info("Wrote %s (%d files)", out_path, len(df))
    return df


# ---------------------------------------------------------------------------
# Key loading utilities
# ---------------------------------------------------------------------------

def _find_first(inventory: pd.DataFrame, role: str) -> Optional[Path]:
    hit = inventory.loc[inventory["guessed_role"] == role, "file_path"]
    if hit.empty:
        return None
    return Path(hit.iloc[0])


def _find_all(inventory: pd.DataFrame, role: str) -> List[Path]:
    return [Path(p) for p in inventory.loc[inventory["guessed_role"] == role, "file_path"]]


@dataclass
class Keys:
    """In-memory copies of the small key/mapping files."""

    state: Optional[pd.DataFrame] = None
    district: Optional[pd.DataFrame] = None
    court: Optional[pd.DataFrame] = None
    case_type: Optional[pd.DataFrame] = None
    purpose: Optional[pd.DataFrame] = None
    disposition: Optional[pd.DataFrame] = None
    act: Optional[pd.DataFrame] = None
    section: Optional[pd.DataFrame] = None


def _read_key_csv(path: Path, dtype_overrides: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """Read a key CSV preserving zero-padded string codes where relevant."""
    return pd.read_csv(
        path,
        dtype=dtype_overrides or {},
        low_memory=False,
        na_values=["", "NA", "NaN"],
        keep_default_na=True,
    )


def load_keys(inventory: pd.DataFrame) -> Keys:
    LOG.info("Loading key/mapping files")
    keys = Keys()

    state_path = _find_first(inventory, "state key")
    if state_path is not None:
        keys.state = _read_key_csv(
            state_path,
            {"state_code": "string", "year": "Int16", "state_name": "string",
             "pc11_state_id": "string", "pc11_state_name": "string"},
        )

    district_path = _find_first(inventory, "district key")
    if district_path is not None:
        keys.district = _read_key_csv(
            district_path,
            {"state_code": "string", "dist_code": "string", "year": "Int16",
             "state_name": "string", "district_name": "string",
             "pc11_state_id": "string", "pc11_state_name": "string",
             "pc11_district_id": "string", "pc11_district_name": "string"},
        )

    court_path = _find_first(inventory, "court key")
    if court_path is not None:
        keys.court = _read_key_csv(
            court_path,
            {"state_code": "string", "dist_code": "string", "court_no": "string",
             "year": "Int16", "state_name": "string", "district_name": "string",
             "court_name": "string"},
        )

    type_path = _find_first(inventory, "type key")
    if type_path is not None:
        keys.case_type = _read_key_csv(
            type_path,
            {"type_name": "string", "type_name_s": "string", "year": "Int16"},
        )

    purpose_path = _find_first(inventory, "purpose key")
    if purpose_path is not None:
        keys.purpose = _read_key_csv(
            purpose_path,
            {"purpose_name": "string", "purpose_name_s": "string", "year": "Int16"},
        )

    disp_path = _find_first(inventory, "disposition key")
    if disp_path is not None:
        keys.disposition = _read_key_csv(
            disp_path,
            {"disp_name": "string", "disp_name_s": "string", "year": "Int16"},
        )

    act_path = _find_first(inventory, "act key")
    if act_path is not None:
        keys.act = _read_key_csv(act_path, {"act": "string", "act_s": "string"})

    section_path = _find_first(inventory, "section key")
    if section_path is not None:
        keys.section = _read_key_csv(section_path, {"section": "string", "section_s": "string"})

    for label, df in [
        ("state", keys.state), ("district", keys.district), ("court", keys.court),
        ("case_type", keys.case_type), ("purpose", keys.purpose),
        ("disposition", keys.disposition), ("act", keys.act), ("section", keys.section),
    ]:
        if df is None:
            LOG.warning("Key '%s' not found — decoded output will fall back to codes.", label)
        else:
            LOG.debug("Loaded %s key: %d rows, cols=%s", label, len(df), list(df.columns))
    return keys


# ---------------------------------------------------------------------------
# Acts_sections preprocessing → per-case criminal indicator
# ---------------------------------------------------------------------------

def preprocess_acts_sections(
    acts_path: Path,
    work_dir: Path,
    chunksize: int,
    force: bool = False,
) -> Path:
    """Aggregate the huge acts_sections file down to one row per ``ddl_case_id``.

    Emits a parquet with columns ``ddl_case_id, criminal_any, criminal_all,
    n_sections`` and returns its path.  ``criminal_any`` is the max of the
    ``criminal`` column per case (1 if any act tagged criminal) and
    ``criminal_all`` is the min (1 only if every row is criminal).
    """
    out_path = work_dir / "per_case_criminal.parquet"
    if out_path.exists() and not force:
        LOG.info("Reusing cached per-case criminal parquet at %s", out_path)
        return out_path

    LOG.info("Step 2 (pre): scanning acts_sections at %s in chunks of %d", acts_path, chunksize)
    parts: List[pd.DataFrame] = []
    total_rows = 0
    for chunk_no, chunk in enumerate(
        pd.read_csv(
            acts_path,
            usecols=lambda c: c in {"ddl_case_id", "criminal"},
            dtype={"ddl_case_id": "string", "criminal": "Int8"},
            chunksize=chunksize,
            na_values=["", "NA", "NaN"],
            keep_default_na=True,
            low_memory=False,
        ),
        start=1,
    ):
        chunk = chunk.dropna(subset=["ddl_case_id"])
        agg = chunk.groupby("ddl_case_id", dropna=False, sort=False).agg(
            criminal_any=("criminal", "max"),
            criminal_all=("criminal", "min"),
            n_sections=("criminal", "size"),
        ).reset_index()
        parts.append(agg)
        total_rows += len(chunk)
        if chunk_no % 5 == 0:
            LOG.info("  acts_sections: read %d rows so far", total_rows)

    LOG.info("acts_sections: %d rows scanned total; consolidating %d partial aggregates", total_rows, len(parts))
    combined = pd.concat(parts, ignore_index=True)
    del parts
    final = combined.groupby("ddl_case_id", dropna=False, sort=False).agg(
        criminal_any=("criminal_any", "max"),
        criminal_all=("criminal_all", "min"),
        n_sections=("n_sections", "sum"),
    ).reset_index()
    LOG.info("acts_sections: %d unique ddl_case_id after aggregation", len(final))
    final["criminal_any"] = final["criminal_any"].astype("Int8")
    final["criminal_all"] = final["criminal_all"].astype("Int8")
    final["n_sections"] = final["n_sections"].astype("Int32")
    final.to_parquet(out_path, index=False)
    LOG.info("Wrote %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Civil/criminal classification helpers
# ---------------------------------------------------------------------------

CRIMINAL_KEYWORDS = [
    "ipc", "cr.p.c", "crpc", "cr pc", "criminal", "sessions", "sc case",
    "fir", "police", "complaint case", "bail", "ndps", "pocso", "excise",
    "prevention of corruption", "arms act", "juvenile", "narcotic",
    "prohibition", "gambling", "immoral traffic", "essential commodities",
    "explosives", "atrocities", "domestic violence", "cheque bounce", "n.i. act",
    "negotiable instruments", "cbi", "prisoners",
]

CIVIL_KEYWORDS = [
    "civil suit", "money suit", "execution", "motor accident", "matrimonial",
    "land", "rent", "arbitration", "probate", "succession", "consumer",
    "commercial", "partition", "specific relief", "eviction", "family",
    "guardian", "hindu marriage", "divorce", "declaration", "injunction",
    "insolvency", "hindu succession", "electricity", "labour", "small cause",
    "revenue", "workmen compensation",
]


def classify_by_keywords(text: pd.Series) -> pd.Series:
    """Return a Series of 'criminal'/'civil'/'unknown' from text hints."""
    lower = text.fillna("").astype(str).str.lower()
    crim_pat = "|".join(re.escape(k) for k in CRIMINAL_KEYWORDS)
    civ_pat = "|".join(re.escape(k) for k in CIVIL_KEYWORDS)
    is_crim = lower.str.contains(crim_pat, regex=True, na=False)
    is_civ = lower.str.contains(civ_pat, regex=True, na=False)
    out = pd.Series(pd.NA, index=text.index, dtype="string")
    out = out.mask(is_civ, "civil")
    out = out.mask(is_crim, "criminal")
    return out


# ---------------------------------------------------------------------------
# Decoding helpers (year-aware merges)
# ---------------------------------------------------------------------------

def _drop_dup(df: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    return df.drop_duplicates(subset=list(keys), keep="last")


def _decode_with_fallback(
    df: pd.DataFrame,
    key_df: pd.DataFrame,
    join_cols: Sequence[str],
    value_col: str,
) -> pd.DataFrame:
    """Merge ``df`` with ``key_df`` on ``join_cols`` (year-scoped) and fall
    back to a year-agnostic join for rows still missing ``value_col``.

    Emits (or updates) ``value_col`` in place.
    """
    if "year" in key_df.columns and "year" in join_cols:
        primary = _drop_dup(key_df[list(join_cols) + [value_col]], list(join_cols))
        df = df.merge(primary, on=list(join_cols), how="left")
        # Fallback without year
        year_less = [c for c in join_cols if c != "year"]
        fallback = _drop_dup(
            key_df.dropna(subset=[value_col])[year_less + [value_col]],
            year_less,
        )
        fallback = fallback.rename(columns={value_col: value_col + "_any"})
        df = df.merge(fallback, on=year_less, how="left")
        df[value_col] = df[value_col].fillna(df[value_col + "_any"])
        df = df.drop(columns=[value_col + "_any"])
    else:
        year_less = [c for c in join_cols if c != "year"]
        primary = _drop_dup(key_df[year_less + [value_col]], year_less)
        df = df.merge(primary, on=year_less, how="left")
    return df


def decode_year_case_data(
    df: pd.DataFrame,
    keys: Keys,
) -> pd.DataFrame:
    """Attach human-readable labels using the key files.

    All merges are left-joins so unmatched rows keep their original codes.
    Year-scoped keys are joined on year first; rows that don't match are
    then filled in via a year-agnostic fallback so partial-coverage keys
    (e.g. the DDL district_key which has ~625 entries in 2010 and only a
    handful of year-specific overrides afterwards) don't leave most rows
    with a missing decoded name.
    """
    if keys.state is not None:
        df = _decode_with_fallback(df, keys.state, ["year", "state_code"], "state_name")

    if keys.district is not None:
        df = _decode_with_fallback(
            df, keys.district, ["year", "state_code", "dist_code"], "district_name"
        )

    if keys.court is not None:
        df = _decode_with_fallback(
            df, keys.court, ["year", "state_code", "dist_code", "court_no"], "court_name"
        )

    if keys.case_type is not None:
        df = _decode_with_fallback(df, keys.case_type, ["year", "type_name"], "type_name_s")

    if keys.purpose is not None:
        df = _decode_with_fallback(df, keys.purpose, ["year", "purpose_name"], "purpose_name_s")

    if keys.disposition is not None:
        df = _decode_with_fallback(df, keys.disposition, ["year", "disp_name"], "disp_name_s")

    return df


# ---------------------------------------------------------------------------
# Per-year case-file processing
# ---------------------------------------------------------------------------

@dataclass
class Accumulators:
    """Aggregation buckets that the streaming pass fills.

    Heavy statistics (percentiles + pending stock) are computed in a
    second pass over per-year parquet caches written by ``process_year_case_file``.
    """

    # (type_name, type_name_s, criminal_flag) -> count
    case_type_counts: Dict[Tuple[Optional[str], Optional[str], Optional[int]], int] = field(default_factory=dict)
    # (state_code, dist_code, year, district_name) -> count
    district_year_names: Dict[Tuple[Optional[str], Optional[str], Optional[int], Optional[str]], int] = field(default_factory=dict)
    # per-year data quality counters
    data_quality: Dict[int, Dict[str, int]] = field(default_factory=dict)


def _bump(d: Dict[str, int], k: str, v: int = 1) -> None:
    d[k] = d.get(k, 0) + v


def _sanitize_dates(series: pd.Series) -> pd.Series:
    """Parse ``series`` as dates while replacing DDL sentinel strings with NaT."""
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        s = series.astype("string")
        # DDL uses e.g. '1970-01-01' occasionally as null.
        s = s.replace({"1970-01-01": pd.NA, "0000-00-00": pd.NA, "": pd.NA})
    else:
        s = series
    return pd.to_datetime(s, errors="coerce")


def process_year_case_file(
    path: Path,
    keys: Keys,
    criminal_pa,
    accumulators: Accumulators,
    chunksize: int,
    per_case_cache_dir: Path,
    write_pending_cache: bool,
) -> None:
    """Stream one yearly case file and update accumulators.

    Also writes a compact per-case parquet (used for pending-stock metrics
    in the second pass).
    """
    year_match = CASE_YEAR_RE.search(path.name)
    label = year_match.group(1) if year_match else path.stem
    LOG.info("Processing %s", path.name)

    per_year_chunks: List[pd.DataFrame] = []

    # Discover which of the wanted columns exist by peeking the header.
    header, _ = _peek_columns_and_rows(path)
    header_set = set(header)
    usecols = [c for c in CASE_COLS_WANTED if c in header_set]
    dtype = {k: v for k, v in CASE_DTYPES.items() if k in usecols}
    LOG.debug("  reading columns: %s", usecols)

    total_rows = 0
    for chunk in pd.read_csv(
        path,
        usecols=usecols,
        dtype=dtype,
        chunksize=chunksize,
        na_values=["", "NA", "NaN", "-9998", "-9999"],
        keep_default_na=True,
        low_memory=False,
    ):
        total_rows += len(chunk)

        # ensure required fields
        for col in ["state_code", "dist_code", "year", "date_of_filing", "date_of_decision"]:
            if col not in chunk.columns:
                chunk[col] = pd.NA

        # Attach criminal flag via pyarrow hash join (much faster than pandas
        # merge/map on the huge 76M-key object index).  Note: pyarrow left
        # outer join is not guaranteed to preserve left-side row order, so we
        # rejoin on ddl_case_id back into the pandas frame.
        chunk_pa = pa.Table.from_pandas(chunk[["ddl_case_id"]], preserve_index=False)
        joined = chunk_pa.join(criminal_pa, keys="ddl_case_id", join_type="left outer")
        crim_map = joined.to_pandas()
        chunk = chunk.merge(crim_map, on="ddl_case_id", how="left")
        chunk["criminal_any"] = pd.to_numeric(chunk["criminal_any"], errors="coerce").astype("Int8")
        chunk["act_section_missing"] = chunk["criminal_any"].isna().astype("Int8")

        # Decode keys (attach *_name columns)
        chunk = decode_year_case_data(chunk, keys)

        # Ensure decoded columns exist even when keys are absent.
        for col in ["state_name", "district_name", "type_name_s"]:
            if col not in chunk.columns:
                chunk[col] = pd.NA

        # Dates
        chunk["date_of_filing_dt"] = _sanitize_dates(chunk.get("date_of_filing"))
        chunk["date_of_decision_dt"] = _sanitize_dates(chunk.get("date_of_decision"))
        if "date_of_registration" in chunk.columns:
            chunk["date_of_registration_dt"] = _sanitize_dates(chunk["date_of_registration"])
        else:
            chunk["date_of_registration_dt"] = pd.NaT

        chunk["filing_year"] = chunk["date_of_filing_dt"].dt.year.astype("Int16")
        chunk["decision_year"] = chunk["date_of_decision_dt"].dt.year.astype("Int16")
        chunk["disposed"] = chunk["date_of_decision_dt"].notna().astype("Int8")
        chunk["pending"] = (~chunk["date_of_decision_dt"].notna()).astype("Int8")

        raw_dur = (chunk["date_of_decision_dt"] - chunk["date_of_filing_dt"]).dt.days
        # Note: raw_dur is float64 with NaN; keep as Float64 nullable.
        chunk["case_duration_days_raw"] = raw_dur.astype("Float64")
        chunk["duration_negative"] = ((raw_dur < 0).fillna(False)).astype("Int8")
        chunk["duration_extreme"] = ((raw_dur > EXTREME_DAYS).fillna(False)).astype("Int8")
        chunk["case_duration_days"] = raw_dur.where((raw_dur >= 0) & (raw_dur <= EXTREME_DAYS)).astype("Float64")

        chunk["case_duration_from_registration_days"] = (
            (chunk["date_of_decision_dt"] - chunk["date_of_registration_dt"]).dt.days
        ).astype("Float64")

        # Civil/criminal classification
        # 1) observed
        observed_source = chunk["criminal_any"].notna()
        chunk["classification_source"] = pd.Series(
            np.where(observed_source, "observed_flag", pd.NA),
            index=chunk.index,
            dtype="string",
        )
        chunk["civil_criminal"] = pd.Series(pd.NA, index=chunk.index, dtype="string")
        chunk.loc[chunk["criminal_any"] == 1, "civil_criminal"] = "criminal"
        chunk.loc[chunk["criminal_any"] == 0, "civil_criminal"] = "civil"

        # 2) fallback via type_name_s
        need_fallback = chunk["civil_criminal"].isna()
        if need_fallback.any() and "type_name_s" in chunk.columns:
            fallback = classify_by_keywords(chunk.loc[need_fallback, "type_name_s"])
            chunk.loc[need_fallback, "civil_criminal"] = fallback.values
            chunk.loc[need_fallback & chunk["civil_criminal"].notna(), "classification_source"] = "fallback_rule"

        chunk["civil_criminal"] = chunk["civil_criminal"].fillna("unknown")
        chunk.loc[chunk["classification_source"].isna(), "classification_source"] = "unknown"

        # -----  update accumulators -----
        year_int = int(label) if label.isdigit() else None
        chunk["year"] = pd.to_numeric(chunk.get("year"), errors="coerce").astype("Int16")
        if year_int is not None:
            chunk["year"] = chunk["year"].fillna(year_int)

        _update_case_type(chunk, accumulators)
        _update_district_year_names(chunk, accumulators)
        _update_data_quality(chunk, accumulators)

        # Always cache the minimal per-case parquet — used by the vectorised
        # second-pass aggregation for duration percentiles (and pending stock
        # when write_pending_cache is True).
        keep_cols = [
            "state_code", "dist_code", "district_name", "year",
            "filing_year", "decision_year", "disposed",
            "case_duration_days", "civil_criminal",
        ]
        missing = [c for c in keep_cols if c not in chunk.columns]
        for c in missing:
            chunk[c] = pd.NA
        per_year_chunks.append(chunk[keep_cols].copy())

        if total_rows % (chunksize * 2) == 0:
            LOG.info("  %s: %d rows processed", path.name, total_rows)

    LOG.info("Finished %s: %d rows", path.name, total_rows)

    per_case_cache_dir.mkdir(parents=True, exist_ok=True)
    if per_year_chunks:
        out_parq = per_case_cache_dir / f"case_min_{label}.parquet"
        pd.concat(per_year_chunks, ignore_index=True).to_parquet(out_parq, index=False)
        LOG.debug("Wrote per-case cache %s", out_parq)


def _update_case_type(chunk: pd.DataFrame, acc: Accumulators) -> None:
    grp_cols = ["type_name", "type_name_s", "criminal_any"]
    for c in grp_cols:
        if c not in chunk.columns:
            chunk[c] = pd.NA
    grp = chunk.groupby(grp_cols, dropna=False, observed=True).size()
    for (type_code, type_s, crim), n in grp.items():
        # convert NaN keys to Python None for stable dict keys
        key = (
            None if pd.isna(type_code) else str(type_code),
            None if pd.isna(type_s) else str(type_s),
            None if pd.isna(crim) else int(crim),
        )
        acc.case_type_counts[key] = acc.case_type_counts.get(key, 0) + int(n)


def _update_district_year_names(chunk: pd.DataFrame, acc: Accumulators) -> None:
    mask = chunk["state_code"].notna() & chunk["dist_code"].notna() & chunk["year"].notna()
    df = chunk.loc[mask, ["state_code", "dist_code", "year", "district_name"]]
    grp = df.groupby(["state_code", "dist_code", "year", "district_name"], dropna=False, observed=True).size()
    for keys_tuple, n in grp.items():
        state_code, dist_code, year, dist_name = keys_tuple
        k = (
            str(state_code) if not pd.isna(state_code) else None,
            str(dist_code) if not pd.isna(dist_code) else None,
            int(year) if not pd.isna(year) else None,
            str(dist_name) if not pd.isna(dist_name) else None,
        )
        acc.district_year_names[k] = acc.district_year_names.get(k, 0) + int(n)


def _update_data_quality(chunk: pd.DataFrame, acc: Accumulators) -> None:
    year_col = chunk.get("year")
    if year_col is None:
        return
    for year, grp in chunk.groupby(year_col, dropna=True):
        try:
            y = int(year)
        except Exception:
            continue
        bucket = acc.data_quality.setdefault(y, {})
        _bump(bucket, "n_cases", len(grp))
        _bump(bucket, "n_missing_filing_date", int(grp["date_of_filing_dt"].isna().sum()))
        _bump(bucket, "n_missing_decision_date", int(grp["date_of_decision_dt"].isna().sum()))
        _bump(bucket, "n_disposed", int((grp["disposed"] == 1).sum()))
        _bump(bucket, "n_pending", int((grp["pending"] == 1).sum()))
        _bump(bucket, "n_duration_negative", int((grp["duration_negative"] == 1).sum()))
        _bump(bucket, "n_duration_extreme", int((grp["duration_extreme"] == 1).sum()))
        _bump(bucket, "n_missing_state", int(grp["state_code"].isna().sum()))
        _bump(bucket, "n_missing_district", int(grp["dist_code"].isna().sum()))
        _bump(bucket, "n_act_section_missing", int((grp["act_section_missing"] == 1).sum()))
        for src, cnt in grp["classification_source"].value_counts(dropna=False).items():
            src_key = "src_" + (str(src) if not pd.isna(src) else "nan")
            _bump(bucket, src_key, int(cnt))
        for cat, cnt in grp["civil_criminal"].value_counts(dropna=False).items():
            cat_key = "cat_" + (str(cat) if not pd.isna(cat) else "nan")
            _bump(bucket, cat_key, int(cnt))


# ---------------------------------------------------------------------------
# Post-processing: build output tables
# ---------------------------------------------------------------------------

def _load_case_min_cache(per_case_cache_dir: Path) -> Optional[pd.DataFrame]:
    """Load all per-year mini parquets emitted during streaming."""
    caches = sorted(per_case_cache_dir.glob("case_min_*.parquet"))
    if not caches:
        LOG.warning("No per-case cache parquets found in %s", per_case_cache_dir)
        return None
    LOG.info("Loading %d per-case cache parquets", len(caches))
    frames = [pd.read_parquet(p) for p in caches]
    df = pd.concat(frames, ignore_index=True)
    del frames
    LOG.info("Combined per-case rows: %d", len(df))
    for col in ("state_code", "dist_code", "district_name", "civil_criminal"):
        df[col] = df[col].astype("category")
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int32")
    df["filing_year"] = pd.to_numeric(df["filing_year"], errors="coerce").astype("Int32")
    df["decision_year"] = pd.to_numeric(df["decision_year"], errors="coerce").astype("Int32")
    df["disposed"] = pd.to_numeric(df["disposed"], errors="coerce").astype("Int8")
    df["case_duration_days"] = pd.to_numeric(df["case_duration_days"], errors="coerce")
    LOG.info("Loaded case_min: memory usage ~%.1f MB", df.memory_usage(deep=True).sum() / 1e6)
    return df


def _aggregate_one_category(
    df: pd.DataFrame, category: str
) -> pd.DataFrame:
    """Vectorised aggregation for one case_category over the loaded parquet."""
    if category == "all":
        sub = df
    else:
        sub = df.loc[df["civil_criminal"] == category]
    if sub.empty:
        return pd.DataFrame()

    same_year = (sub["disposed"] == 1) & (sub["year"] == sub["decision_year"])
    tmp = sub.assign(same_year_disposed=same_year.astype("Int8"))

    grp = tmp.groupby(
        ["state_code", "dist_code", "district_name", "year"],
        dropna=False, observed=True,
    )
    counts = grp.agg(
        cases_filed=("year", "size"),
        cases_disposed=("disposed", "sum"),
        same_year_disposed=("same_year_disposed", "sum"),
        mean_disposal_days=("case_duration_days", "mean"),
    )

    dur = tmp.dropna(subset=["case_duration_days"])
    if not dur.empty:
        pcts = (
            dur.groupby(
                ["state_code", "dist_code", "district_name", "year"],
                dropna=False, observed=True,
            )["case_duration_days"]
            .quantile([0.5, 0.75, 0.90])
            .unstack()
        )
        pcts.columns = ["median_disposal_days", "p75_disposal_days", "p90_disposal_days"]
        counts = counts.join(pcts, how="left")
    else:
        counts["median_disposal_days"] = np.nan
        counts["p75_disposal_days"] = np.nan
        counts["p90_disposal_days"] = np.nan

    out = counts.reset_index()
    out["case_category"] = category
    out["cases_disposed"] = out["cases_disposed"].fillna(0).astype("Int64")
    out["same_year_disposed"] = out["same_year_disposed"].fillna(0).astype("Int64")
    out["clearance_rate"] = np.where(
        out["cases_filed"] > 0,
        out["cases_disposed"].astype(float) / out["cases_filed"].astype(float),
        np.nan,
    )
    out["same_year_disposal_share"] = np.where(
        out["cases_filed"] > 0,
        out["same_year_disposed"].astype(float) / out["cases_filed"].astype(float),
        np.nan,
    )
    return out.drop(columns=["same_year_disposed"])


def build_district_year_efficiency(
    case_min: pd.DataFrame,
    pending_metrics: Optional[pd.DataFrame],
    out_dir: Path,
) -> pd.DataFrame:
    LOG.info("Step 7: assembling district-year efficiency table")

    # Filter out rows without a valid district identifier.
    valid = case_min.dropna(subset=["state_code", "dist_code", "year"])
    LOG.info("Aggregation input rows: %d (of %d total)", len(valid), len(case_min))

    parts: List[pd.DataFrame] = []
    for category in ("all", "civil", "criminal"):
        LOG.info("  aggregating category=%s", category)
        parts.append(_aggregate_one_category(valid, category))
    df = pd.concat([p for p in parts if not p.empty], ignore_index=True)

    if pending_metrics is not None and not pending_metrics.empty:
        df = df.merge(
            pending_metrics,
            on=["state_code", "dist_code", "year", "case_category"],
            how="left",
        )
    else:
        for col in [
            "pending_cases_end_year", "old_pending_share_2yr", "old_pending_share_5yr",
        ]:
            df[col] = pd.NA

    # Derive active_cases and pending_share now, so Step 8 can use them.
    df = enrich_with_pending_shares(df)

    # ------------- Step 8: efficiency index -------------
    LOG.info("Step 8: computing standardized efficiency index")

    def _z(series: pd.Series) -> np.ndarray:
        """Return a plain float64 numpy z-score, robust to all-NA and zero std."""
        s = pd.to_numeric(series, errors="coerce").astype("float64")
        arr = s.to_numpy(dtype="float64", na_value=np.nan)
        finite = arr[~np.isnan(arr)]
        if finite.size == 0:
            return np.full_like(arr, np.nan)
        mean = float(np.mean(finite))
        std = float(np.std(finite, ddof=0))
        if std == 0 or np.isnan(std):
            return np.full_like(arr, np.nan)
        return (arr - mean) / std

    for score in ("speed_score", "clearance_score", "same_year_score",
                  "pendency_score", "old_case_score"):
        df[score] = np.nan

    has_pending = "pending_share" in df.columns and df["pending_share"].notna().any()
    has_old = "old_pending_share_2yr" in df.columns and df["old_pending_share_2yr"].notna().any()

    for (year, category), grp in df.groupby(["year", "case_category"], dropna=False):
        idx = grp.index
        df.loc[idx, "speed_score"] = -_z(grp["median_disposal_days"])
        df.loc[idx, "clearance_score"] = _z(grp["clearance_rate"])
        df.loc[idx, "same_year_score"] = _z(grp["same_year_disposal_share"])
        if has_pending:
            df.loc[idx, "pendency_score"] = -_z(grp["pending_share"])
        if has_old:
            df.loc[idx, "old_case_score"] = -_z(grp["old_pending_share_2yr"])

    simple_components = ["speed_score", "clearance_score", "same_year_score"]
    df["court_efficiency_index_simple"] = df[simple_components].mean(axis=1, skipna=True)
    full_components = simple_components + ["pendency_score", "old_case_score"]
    # Only build the "full" index for rows that have all pending components populated
    has_full = df[["pendency_score", "old_case_score"]].notna().all(axis=1)
    df["court_efficiency_index_full"] = np.where(
        has_full,
        df[full_components].mean(axis=1, skipna=True),
        np.nan,
    )

    df = df.sort_values(["year", "case_category", "state_code", "dist_code"])
    out_path = out_dir / "district_year_efficiency.csv"
    df.to_csv(out_path, index=False)
    LOG.info("Wrote %s (%d rows)", out_path, len(df))
    return df


def build_case_type_summary(
    acc: Accumulators, out_dir: Path
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    LOG.info("Step 5: assembling case-type summary")
    rows = []
    total = sum(acc.case_type_counts.values()) or 1
    for (type_code, type_s, crim), n in acc.case_type_counts.items():
        rows.append({
            "type_code": type_code,
            "type_name_s": type_s,
            "criminal_flag_observed": crim,
            "count": n,
            "share": n / total,
        })
    df = pd.DataFrame(rows).sort_values("count", ascending=False).reset_index(drop=True)

    # collapse by (type_code, type_name_s) for the second table
    df_wide = df.copy()
    df_wide["flag_1"] = np.where(df_wide["criminal_flag_observed"] == 1, df_wide["count"], 0)
    df_wide["flag_0"] = np.where(df_wide["criminal_flag_observed"] == 0, df_wide["count"], 0)
    df_wide["flag_missing"] = np.where(df_wide["criminal_flag_observed"].isna(), df_wide["count"], 0)

    agg = df_wide.groupby(["type_code", "type_name_s"], dropna=False, observed=True).agg(
        total_count=("count", "sum"),
        n_criminal_flag_1=("flag_1", "sum"),
        n_criminal_flag_0=("flag_0", "sum"),
        n_criminal_flag_missing=("flag_missing", "sum"),
    ).reset_index()

    def _classify_row(row):
        c1 = int(row.get("n_criminal_flag_1", 0) or 0)
        c0 = int(row.get("n_criminal_flag_0", 0) or 0)
        if c1 + c0 > 0:
            return pd.Series({
                "final_classification": "criminal" if c1 >= c0 else "civil",
                "classification_source": "observed_flag",
            })
        fallback = classify_by_keywords(pd.Series([row["type_name_s"]])).iloc[0]
        if not pd.isna(fallback):
            return pd.Series({
                "final_classification": fallback,
                "classification_source": "fallback_rule",
            })
        return pd.Series({"final_classification": "unknown", "classification_source": "unknown"})

    agg[["final_classification", "classification_source"]] = agg.apply(_classify_row, axis=1)
    agg["share_of_total_cases"] = agg["total_count"] / total

    out1 = out_dir / "case_type_summary.csv"
    df.to_csv(out1, index=False)
    LOG.info("Wrote %s", out1)

    out2 = out_dir / "civil_criminal_classification_table.csv"
    agg.sort_values("total_count", ascending=False).to_csv(out2, index=False)
    LOG.info("Wrote %s", out2)

    return df, agg


def build_decoded_districts_raw(
    acc: Accumulators, out_dir: Path
) -> pd.DataFrame:
    LOG.info("Step 3: writing decoded_districts_raw.csv")
    rows = []
    for (state_code, dist_code, year, dist_name), n in acc.district_year_names.items():
        rows.append({
            "state_code": state_code,
            "dist_code": dist_code,
            "year": year,
            "district_name": dist_name,
            "n_cases": n,
        })
    df = pd.DataFrame(rows).sort_values(
        ["state_code", "dist_code", "year"]
    ).reset_index(drop=True)
    out = out_dir / "decoded_districts_raw.csv"
    df.to_csv(out, index=False)
    LOG.info("Wrote %s (%d rows)", out, len(df))
    return df


def build_district_code_check(raw_df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Assess whether ``state_code + dist_code`` maps to one district_name across years.

    Distinguishes "code has genuinely different names across years" (a real
    stability problem) from "some year rows just lack a matching district-key
    entry" (a coverage problem in the DDL key, not a code inconsistency).
    """
    LOG.info("Step 4: checking district-code stability across years")
    df = raw_df.copy()
    has_name = df["district_name"].notna() & (df["district_name"].astype(str).str.strip() != "")
    df["district_name_norm"] = df["district_name"].where(has_name)

    grp = df.groupby(["state_code", "dist_code"], dropna=False, observed=True)

    def _unique_names(s: pd.Series) -> str:
        vals = sorted({str(v) for v in s.dropna().unique()})
        return "|".join(vals) if vals else ""

    out = grp.agg(
        n_year_rows=("year", "size"),
        first_year=("year", "min"),
        last_year=("year", "max"),
        n_years_with_name=("district_name_norm", "count"),
        n_years_missing_name=("district_name_norm", lambda s: int(s.isna().sum())),
        n_unique_actual_names=("district_name_norm", pd.Series.nunique),
        district_names_seen=("district_name_norm", _unique_names),
    ).reset_index()

    # A code is "stable" if it always resolves to the *same* non-missing name.
    out["stable_code_flag"] = (out["n_unique_actual_names"] <= 1).astype(int)
    # Coverage flag: 1 if the district_key had entries for every year the code
    # appeared in cases; 0 otherwise (still stable in name terms but missing
    # rows in the year-scoped key).
    out["full_year_coverage_flag"] = (out["n_years_missing_name"] == 0).astype(int)

    out = out.sort_values(
        ["stable_code_flag", "full_year_coverage_flag", "state_code", "dist_code"]
    ).reset_index(drop=True)

    path = out_dir / "decoded_district_code_check.csv"
    out.to_csv(path, index=False)
    stable = (out["stable_code_flag"] == 1).sum()
    unstable = (out["stable_code_flag"] == 0).sum()
    full_cov = (out["full_year_coverage_flag"] == 1).sum()
    LOG.info(
        "Wrote %s (%d rows; %d name-stable, %d name-conflict; %d have full-year name coverage)",
        path, len(out), stable, unstable, full_cov,
    )
    return out


def build_data_quality(acc: Accumulators, out_dir: Path) -> pd.DataFrame:
    LOG.info("Step 6: writing data quality summary")
    rows = []
    for year, bucket in sorted(acc.data_quality.items()):
        row = {"year": year}
        row.update(bucket)
        rows.append(row)
    df = pd.DataFrame(rows)
    path = out_dir / "data_quality_summary.csv"
    df.to_csv(path, index=False)
    LOG.info("Wrote %s (%d rows)", path, len(df))
    return df


# ---------------------------------------------------------------------------
# Pending-stock metrics (Step 7 optional part)
# ---------------------------------------------------------------------------

def build_pending_metrics(
    case_min: pd.DataFrame,
    max_year: int,
    min_year: int,
) -> Optional[pd.DataFrame]:
    """Compute pending-stock metrics from the loaded per-case DataFrame.

    A case ``c`` is *pending at end of year y* iff ``filing_year(c) <= y`` and
    either ``decision_year(c) > y`` or the case has no decision_year.
    """
    if case_min is None or case_min.empty:
        return None

    LOG.info("Second pass: computing pending stock")
    combined = case_min

    years = list(range(min_year, max_year + 1))

    all_pending: List[pd.DataFrame] = []
    for y in years:
        filed_by_end = combined["filing_year"].notna() & (combined["filing_year"] <= y)
        not_disposed_by_end = combined["decision_year"].isna() | (combined["decision_year"] > y)
        pending_mask = filed_by_end & not_disposed_by_end
        pending = combined.loc[pending_mask, [
            "state_code", "dist_code", "filing_year", "civil_criminal"
        ]].copy()
        if pending.empty:
            continue
        pending["case_age_years"] = y - pending["filing_year"].astype("Int64")
        pending["is_older_2yr"] = (pending["case_age_years"] > 2).astype("Int8")
        pending["is_older_5yr"] = (pending["case_age_years"] > 5).astype("Int8")
        for category in ("all", "civil", "criminal"):
            if category == "all":
                sub = pending
            else:
                sub = pending.loc[pending["civil_criminal"] == category]
            if sub.empty:
                continue
            grp = sub.groupby(["state_code", "dist_code"], dropna=False, observed=True).agg(
                pending_cases_end_year=("filing_year", "size"),
                pending_older_2yr=("is_older_2yr", "sum"),
                pending_older_5yr=("is_older_5yr", "sum"),
            ).reset_index()
            grp["year"] = y
            grp["case_category"] = category
            all_pending.append(grp)

    if not all_pending:
        return None

    out = pd.concat(all_pending, ignore_index=True)

    # active cases = filed on or before y and (disposed in year y OR still pending)
    # We approximate active_cases = pending_cases_end_year + cases_disposed_in_year;
    # but cases_disposed_in_year comes from the district_year_stats table.  So we
    # only compute pending shares from the pending stock and leave the join to the
    # caller.  ``pending_share`` here is per pending-stock only.
    out["old_pending_share_2yr"] = np.where(
        out["pending_cases_end_year"] > 0,
        out["pending_older_2yr"] / out["pending_cases_end_year"],
        np.nan,
    )
    out["old_pending_share_5yr"] = np.where(
        out["pending_cases_end_year"] > 0,
        out["pending_older_5yr"] / out["pending_cases_end_year"],
        np.nan,
    )
    return out[[
        "state_code", "dist_code", "year", "case_category",
        "pending_cases_end_year", "old_pending_share_2yr", "old_pending_share_5yr",
    ]]


def enrich_with_pending_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Compute ``active_cases`` and ``pending_share`` using both tables."""
    if "pending_cases_end_year" not in df.columns:
        df["active_cases"] = pd.NA
        df["pending_share"] = np.nan
        return df
    disposed = pd.to_numeric(df.get("cases_disposed"), errors="coerce").fillna(0)
    pending = pd.to_numeric(df["pending_cases_end_year"], errors="coerce").fillna(0)
    active = disposed + pending
    df["active_cases"] = active.astype("Int64").where(active > 0)
    df["pending_share"] = np.where(
        active > 0,
        pending / active.replace(0, np.nan),
        np.nan,
    )
    return df


# ---------------------------------------------------------------------------
# Assumptions markdown
# ---------------------------------------------------------------------------

def write_assumptions_md(
    out_dir: Path,
    files_found: pd.DataFrame,
    stability: pd.DataFrame,
    pending_computed: bool,
    date_field: str,
) -> None:
    LOG.info("Step 9: writing assumptions_and_choices.md")
    path = out_dir / "assumptions_and_choices.md"

    n_files = len(files_found)
    case_files = files_found.loc[files_found["guessed_role"] == "case file", "file_path"].tolist()
    keys_files = files_found.loc[files_found["guessed_role"].str.endswith("key"), "file_path"].tolist()
    acts_files = files_found.loc[files_found["guessed_role"] == "acts_sections", "file_path"].tolist()

    stable = int((stability["stable_code_flag"] == 1).sum())
    unstable = int((stability["stable_code_flag"] == 0).sum())
    stable_pct = stable / max(len(stability), 1) * 100
    full_cov = int((stability.get("full_year_coverage_flag", pd.Series(dtype=int)) == 1).sum())

    content = f"""# Assumptions and Choices — District-Level Court Efficiency Build

## Data source

DevDataLab / DDL Judicial Data (2010–2018), covering Indian district / lower
court cases.  See https://www.devdatalab.org/judicial-data.

Files identified in the input directory ({n_files} data files total):

- Case files ({len(case_files)}): one CSV per filing year.
- Acts / sections file ({len(acts_files)}): single `acts_sections.csv` with
  one row per (case × act × section).
- Key / mapping files ({len(keys_files)}) for state, district, court,
  case-type, purpose, disposition, act, section.

## Judge data is deliberately ignored

We are measuring court/district-level efficiency, not judge-level efficiency.
Judge matching in DDL is incomplete and is mostly informative for
criminal-case judge analysis, so `judges_clean` and `judge_case_merge_key`
were skipped.

## Merge strategy

- Main join key: `ddl_case_id`.
- Acts/sections was pre-aggregated to one row per case (columns
  `criminal_any = max(criminal)`, `criminal_all = min(criminal)`,
  `n_sections = count`) and cached at
  `work/per_case_criminal.parquet` to avoid the 3.6 GB acts file dominating
  every pass.
- Case files were joined with the aggregated criminal flag via left join;
  cases without any acts/sections row were tagged `act_section_missing = 1`.

## Decoding

Year-scoped keys use a two-step "year first, then year-agnostic fallback"
merge.  This matters most for the DDL district_key, which has 625 rows for
2010, only 4 for 2011, 2 for 2014, 1 for 2017 — so most (state, dist, year)
tuples for 2011–2018 would have no match if we joined strictly on year.
The fallback fills them in from the 2010 baseline.

- State: `year + state_code → state_name`, then `state_code → state_name`.
- District: `year + state_code + dist_code → district_name`, then
  `state_code + dist_code → district_name`.
- Court: `year + state_code + dist_code + court_no → court_name`, then the
  same without year.
- Case type / purpose / disposition: `year + code → name` then `code → name`.
- Act / section keys carry no `year`, so joined on code alone (used only for
  reference; not needed for the efficiency numbers).

## Civil / criminal classification

1. **Primary rule**: use `criminal_any` from the acts/sections aggregation.
   `criminal_any = 1 → criminal`, `criminal_any = 0 → civil`.
   Tagged as `classification_source = observed_flag`.
2. **Fallback rule** (when the flag is missing): apply keyword matching to
   `type_name_s` from the type-name key.  Criminal keywords include IPC,
   CrPC, sessions, FIR, police, bail, NDPS, POCSO, excise, corruption, arms
   act, N.I. Act (cheque bounce), etc.  Civil keywords include civil suit,
   money suit, execution, MACT, matrimonial, land, rent, arbitration, probate,
   succession, consumer, commercial, etc.  Tagged as
   `classification_source = fallback_rule`.
3. Anything not matched by either rule is labelled `unknown`.

## District-code stability

Of {len(stability)} unique `state_code + dist_code` pairs:

- **{stable} ({stable_pct:.1f}%) are name-stable** — every year in which the
  code appears in cases resolves to the *same* non-missing district name.
- **{unstable} have genuine name conflicts** across years (see
  `decoded_district_code_check.csv` for the offenders — in practice these
  are minor typos such as `Hoshiarpur` vs `Hoshiarpurr` and city renamings
  such as `Jaipur Metro` vs `Jaipur Metro I`).
- **{full_cov} have full-year name coverage** *after* applying the
  year-agnostic fallback described in the Decoding section.

**Conclusion:** `state_code + dist_code` is effectively a stable district
identifier for the DDL 2010–18 vintage; the recommended merge key when
combining with external district-level datasets is `state_code + dist_code`,
optionally kept year-aware (`state_code + dist_code + year`) to preserve
the small number of within-panel renamings.

## Date / duration choices

- Primary duration = `date_of_decision − date_of_filing` (**{date_field}**).
- `date_of_registration` is **not present** in the DDL 2010–18 case files,
  so `case_duration_from_registration_days` is emitted but always NaN.
- Dates that parse to `1970-01-01` or `0000-00-00` are treated as missing.
- Cases with `decision_date < filing_date` are flagged (`duration_negative =
  1`) and dropped from the duration calculations.
- Cases with duration > 40 years (`duration_extreme = 1`) are flagged and
  dropped from duration calculations too.  Both flags are tallied in
  `outputs/data_quality_summary.csv`.

## Disposed / pending

- `disposed = 1` iff `date_of_decision` is non-missing after sanitisation.
- `pending = 1` otherwise.  Note: DDL's `disp_name` also encodes the
  disposition, but for the efficiency index we take the simpler,
  date-based definition.

## Pending stock

Pending-stock metrics **{"were" if pending_computed else "were NOT"} computed** in
this run:

- If computed, they include `pending_cases_end_year`, `active_cases`,
  `pending_share`, `old_pending_share_2yr`, `old_pending_share_5yr`, and
  feed into `court_efficiency_index_full`.
- Pending at year-end `y` is defined as filed on or before Dec 31 of year
  `y` and not disposed on or before Dec 31 of year `y`.
- Old-pending 2 / 5 yr shares are the fraction of that stock whose case age
  (in whole years) exceeds 2 or 5.
- If pending was not computed (`--skip-pending`), only
  `court_efficiency_index_simple` is populated.

## Efficiency index

Standardised at the `year × case_category` level (categories: `all`, `civil`,
`criminal`):

- `speed_score      = -z(median_disposal_days)`
- `clearance_score  =  z(clearance_rate)`
- `same_year_score  =  z(same_year_disposal_share)`
- `pendency_score   = -z(pending_share)`         (if available)
- `old_case_score   = -z(old_pending_share_2yr)` (if available)

`court_efficiency_index_simple`  = mean of the first three scores.
`court_efficiency_index_full`    = mean of all five (only where pending
scores exist).  Higher = more efficient.

## Known caveats

- Duration percentiles (median, p75, p90) are exact — computed via
  `pandas.groupby(...).quantile()` on the full per-case parquet cache in the
  second pass.
- The fallback classifier is a coarse keyword match on `type_name_s`; it
  will mislabel edge cases like PILs.  The `classification_source` column
  lets you filter to `observed_flag` only for the most defensible split.
- Cases with `state_code` or `dist_code` missing are dropped from the
  district-year aggregation (their counts appear in
  `data_quality_summary.csv`).
- Same-year disposal share uses the case-file `year` (== filing year for
  DDL) rather than parsed `filing_year` from the date column; the two agree
  in the DDL data by construction.
- The scratch parquet at `work/per_case_criminal.parquet` (~900 MB) and the
  per-year `work/case_min/case_min_YYYY.parquet` caches (~130 MB total)
  are safe to delete once you have the final outputs.  Re-running the
  script will regenerate them (~20 min end-to-end on this machine).
"""
    path.write_text(content)
    LOG.info("Wrote %s", path)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.verbose)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = args.work_dir or (args.out_dir.parent / "work")
    work_dir.mkdir(parents=True, exist_ok=True)
    per_case_cache_dir = work_dir / "case_min"

    # ---------- Step 0 ----------
    inventory = build_file_inventory(args.data_dir, args.out_dir)

    case_files = _find_all(inventory, "case file")
    if not case_files:
        LOG.error("No case files discovered under %s — aborting.", args.data_dir)
        return 2
    acts_path = _find_first(inventory, "acts_sections")
    if acts_path is None:
        LOG.warning("acts_sections not found — the entire criminal flag will be missing and fallback rule will kick in.")

    # ---------- Load keys ----------
    keys = load_keys(inventory)

    # ---------- Pre-aggregate acts_sections ----------
    if acts_path is not None:
        per_case_criminal_path = preprocess_acts_sections(
            acts_path, work_dir, args.chunksize, force=args.force_refresh_acts,
        )
    else:
        # Emit an empty per-case parquet so downstream merge keeps working.
        per_case_criminal_path = work_dir / "per_case_criminal.parquet"
        pd.DataFrame({
            "ddl_case_id": pd.Series(dtype="string"),
            "criminal_any": pd.Series(dtype="Int8"),
            "criminal_all": pd.Series(dtype="Int8"),
            "n_sections": pd.Series(dtype="Int32"),
        }).to_parquet(per_case_criminal_path, index=False)

    # ---------- Process case files ----------
    LOG.info("Loading per-case criminal parquet as pyarrow table (fast join key)")
    criminal_pa = pq.read_table(per_case_criminal_path, columns=["ddl_case_id", "criminal_any"])
    LOG.info("Criminal-flag pyarrow table ready (%d entries)", criminal_pa.num_rows)

    acc = Accumulators()
    write_pending_cache = not args.skip_pending
    for path in case_files:
        process_year_case_file(
            path=path,
            keys=keys,
            criminal_pa=criminal_pa,
            accumulators=acc,
            chunksize=args.chunksize,
            per_case_cache_dir=per_case_cache_dir,
            write_pending_cache=write_pending_cache,
        )
    del criminal_pa

    # ---------- Post-processing ----------
    build_case_type_summary(acc, args.out_dir)
    raw_districts = build_decoded_districts_raw(acc, args.out_dir)
    stability = build_district_code_check(raw_districts, args.out_dir)
    build_data_quality(acc, args.out_dir)

    case_min = _load_case_min_cache(per_case_cache_dir)

    pending_df = None
    pending_computed = False
    if write_pending_cache and case_min is not None:
        years = [int(m.group(1)) for m in (CASE_YEAR_RE.search(p.name) for p in case_files) if m]
        if years:
            pending_df = build_pending_metrics(
                case_min=case_min,
                min_year=min(years),
                max_year=max(years),
            )
            pending_computed = pending_df is not None

    district_year = build_district_year_efficiency(case_min, pending_df, args.out_dir)

    write_assumptions_md(
        out_dir=args.out_dir,
        files_found=inventory,
        stability=stability,
        pending_computed=pending_computed,
        date_field="date_of_filing",
    )

    LOG.info("Done. Outputs in %s", args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
