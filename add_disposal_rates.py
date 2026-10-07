"""Add period-based Disposal Rate 1 and Disposal Rate 2 to the court-efficiency panel.

Disposal Rate 1 = cases disposed in year t / new cases filed in year t
Disposal Rate 2 = cases disposed in year t / (pending end of year t-1 + new cases filed in year t)

Numerator uses DECISION year (period disposals), unlike the existing clearance_rate
which is filing-cohort eventual disposal.
"""
from __future__ import annotations

import re
import tarfile
from pathlib import Path

import numpy as np
import pandas as pd

TAR_PATH = Path(r"C:\ddl_data\cases.tar.gz")
KEYS_DIR = Path(r"C:\ddl_data\csv\keys")
EFF_PATH = Path(r"C:\Users\anubh\Downloads\district_year_efficiency.csv")
OUT_DIR = Path(r"C:\Users\anubh\OneDrive\Desktop\New folder (3)\ASI")
DOWNLOADS = Path(r"C:\Users\anubh\Downloads")
CHUNK = 1_000_000

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
    lower = text.fillna("").astype(str).str.lower()
    crim_pat = "|".join(re.escape(k) for k in CRIMINAL_KEYWORDS)
    civ_pat = "|".join(re.escape(k) for k in CIVIL_KEYWORDS)
    is_crim = lower.str.contains(crim_pat, regex=True, na=False)
    is_civ = lower.str.contains(civ_pat, regex=True, na=False)
    out = pd.Series(pd.NA, index=text.index, dtype="string")
    out = out.mask(is_civ, "civil")
    out = out.mask(is_crim, "criminal")
    return out.fillna("unknown")


def load_type_lookup() -> pd.DataFrame:
    path = KEYS_DIR / "type_name_key.csv"
    t = pd.read_csv(path, dtype={"type_name": "string", "type_name_s": "string", "year": "Int16"})
    # year-agnostic fallback: last label per type code
    return (
        t.dropna(subset=["type_name_s"])
        .drop_duplicates(subset=["type_name"], keep="last")
        [["type_name", "type_name_s"]]
    )


def sanitize_dates(s: pd.Series) -> pd.Series:
    if pd.api.types.is_string_dtype(s) or s.dtype == object:
        s = s.astype("string").replace({"1970-01-01": pd.NA, "0000-00-00": pd.NA, "": pd.NA})
    return pd.to_datetime(s, errors="coerce")


def accumulate_from_chunk(chunk: pd.DataFrame, type_lookup: pd.DataFrame, buckets: dict) -> None:
    chunk = chunk.copy()
    for c in ["state_code", "dist_code", "type_name", "date_of_filing", "date_of_decision"]:
        if c not in chunk.columns:
            chunk[c] = pd.NA

    chunk["state_code"] = chunk["state_code"].astype("string").str.zfill(2)
    chunk["dist_code"] = chunk["dist_code"].astype("string").str.zfill(2)
    chunk["type_name"] = chunk["type_name"].astype("string")

    chunk = chunk.merge(type_lookup, on="type_name", how="left")
    chunk["civil_criminal"] = classify_by_keywords(chunk["type_name_s"])

    filing = sanitize_dates(chunk["date_of_filing"])
    decision = sanitize_dates(chunk["date_of_decision"])
    chunk["filing_year"] = filing.dt.year.astype("Int32")
    chunk["decision_year"] = decision.dt.year.astype("Int32")

    # Filings by filing year
    filed = chunk.dropna(subset=["state_code", "dist_code", "filing_year"])
    for cat in ("all", "civil", "criminal"):
        sub = filed if cat == "all" else filed.loc[filed["civil_criminal"] == cat]
        if sub.empty:
            continue
        g = sub.groupby(["state_code", "dist_code", "filing_year"], observed=True).size()
        key = ("filed", cat)
        buckets[key] = buckets.get(key, g).add(g, fill_value=0)

    # Period disposals by decision year
    disposed = chunk.dropna(subset=["state_code", "dist_code", "decision_year"])
    for cat in ("all", "civil", "criminal"):
        sub = disposed if cat == "all" else disposed.loc[disposed["civil_criminal"] == cat]
        if sub.empty:
            continue
        g = sub.groupby(["state_code", "dist_code", "decision_year"], observed=True).size()
        key = ("disposed_period", cat)
        buckets[key] = buckets.get(key, g).add(g, fill_value=0)


def stream_tar(type_lookup: pd.DataFrame) -> dict:
    buckets: dict = {}
    with tarfile.open(TAR_PATH, "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.name.endswith(".csv") and "cases_" in m.name]
        members = sorted(members, key=lambda m: m.name)
        for m in members:
            print(f"Processing {m.name} ({m.size/1e9:.2f} GB uncompressed)...", flush=True)
            f = tf.extractfile(m)
            if f is None:
                continue
            reader = pd.read_csv(
                f,
                usecols=lambda c: c in {
                    "state_code", "dist_code", "type_name",
                    "date_of_filing", "date_of_decision",
                },
                dtype={
                    "state_code": "string",
                    "dist_code": "string",
                    "type_name": "string",
                },
                chunksize=CHUNK,
                na_values=["", "NA", "NaN", "-9998", "-9999"],
                low_memory=False,
            )
            n = 0
            for chunk in reader:
                n += len(chunk)
                accumulate_from_chunk(chunk, type_lookup, buckets)
                if n % (CHUNK * 2) == 0:
                    print(f"  {m.name}: {n:,} rows", flush=True)
            print(f"  Finished {m.name}: {n:,} rows", flush=True)
    return buckets


def stacks_to_frames(buckets: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    filed_parts = []
    disp_parts = []
    for (kind, cat), series in buckets.items():
        df = series.rename("n").reset_index()
        df["case_category"] = cat
        if kind == "filed":
            df = df.rename(columns={"filing_year": "year", "n": "new_cases_filed"})
            filed_parts.append(df)
        else:
            df = df.rename(columns={"decision_year": "year", "n": "cases_disposed_in_year"})
            disp_parts.append(df)
    filed = pd.concat(filed_parts, ignore_index=True)
    disp = pd.concat(disp_parts, ignore_index=True)
    return filed, disp


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading type lookup...")
    type_lookup = load_type_lookup()
    print(f"Type lookup rows: {len(type_lookup)}")

    print("Streaming cases from tarball (this takes a while)...")
    buckets = stream_tar(type_lookup)
    filed, disp = stacks_to_frames(buckets)
    filed.to_csv(OUT_DIR / "period_filings_by_district_year.csv", index=False)
    disp.to_csv(OUT_DIR / "period_disposals_by_district_year.csv", index=False)
    print(f"Filed aggregates: {len(filed)} rows; period disposals: {len(disp)} rows")

    eff = pd.read_csv(EFF_PATH)
    eff["state_code"] = eff["state_code"].astype(str).str.zfill(2)
    eff["dist_code"] = eff["dist_code"].astype(str).str.zfill(2)
    filed["state_code"] = filed["state_code"].astype(str).str.zfill(2)
    filed["dist_code"] = filed["dist_code"].astype(str).str.zfill(2)
    disp["state_code"] = disp["state_code"].astype(str).str.zfill(2)
    disp["dist_code"] = disp["dist_code"].astype(str).str.zfill(2)
    filed["year"] = filed["year"].astype(int)
    disp["year"] = disp["year"].astype(int)

    # Prefer existing cases_filed from efficiency panel (same construction as original);
    # period disposals are the new numerator.
    out = eff.merge(
        disp[["state_code", "dist_code", "year", "case_category", "cases_disposed_in_year"]],
        on=["state_code", "dist_code", "year", "case_category"],
        how="left",
    )
    out["cases_disposed_in_year"] = out["cases_disposed_in_year"].fillna(0).astype("Int64")

    # Pending at end of t-1
    pend = out[["state_code", "dist_code", "year", "case_category", "pending_cases_end_year"]].copy()
    pend["year"] = pend["year"] + 1
    pend = pend.rename(columns={"pending_cases_end_year": "pending_cases_end_prev_year"})
    out = out.merge(pend, on=["state_code", "dist_code", "year", "case_category"], how="left")

    # Disposal Rate 1 = period disposals / filings in t
    filings = pd.to_numeric(out["cases_filed"], errors="coerce")
    period_disp = pd.to_numeric(out["cases_disposed_in_year"], errors="coerce")
    out["disposal_rate_1"] = np.where(filings > 0, period_disp / filings, np.nan)

    # Disposal Rate 2 = period disposals / (pending t-1 + filings t)
    # For first year in panel (2010), pending t-1 is unknown → leave NaN
    pend_prev = pd.to_numeric(out["pending_cases_end_prev_year"], errors="coerce")
    denom2 = pend_prev.fillna(0) + filings.fillna(0)
    # Only compute when we have a real prior pending (year > min) OR pend_prev observed
    has_prior = out["pending_cases_end_prev_year"].notna()
    out["disposal_rate_2"] = np.where(
        has_prior & (denom2 > 0),
        period_disp / denom2,
        np.nan,
    )

    # Rename for clarity in deliverable
    # Keep originals; add clear labels in a README note

    out_path = OUT_DIR / "district_year_efficiency_with_disposal_rates.csv"
    out.to_csv(out_path, index=False)
    print(f"Wrote {out_path} ({len(out)} rows)")

    # Sanity
    print("\n=== SANITY (case_category=all) ===")
    all_ = out[out.case_category == "all"]
    print(all_[["year", "disposal_rate_1", "disposal_rate_2"]].groupby("year").agg(["mean", "median", "min", "max"]).round(3))
    print("share disposal_rate_1 > 1:", float((all_.disposal_rate_1 > 1).mean()))
    print("share disposal_rate_2 > 1:", float((all_.disposal_rate_2 > 1).fillna(False).mean()))
    print("2010 disposal_rate_2 non-null:", int(all_.loc[all_.year == 2010, "disposal_rate_2"].notna().sum()))

    # Also update Shivangi merged file
    update_shivangi_merge(out)


def update_shivangi_merge(eff_new: pd.DataFrame) -> None:
    """Attach the two new rates onto Shivangi's merged district-year file."""
    import sys
    sys.path.insert(0, str(OUT_DIR))
    # Reuse crosswalk from prior merge if present
    merged_path = OUT_DIR / "district_year_with_efficiency.dta"
    if not merged_path.exists():
        merged_path = DOWNLOADS / "district_year_with_efficiency.dta"
    base = pd.read_stata(merged_path)
    print(f"\nUpdating Shivangi merge file ({len(base)} rows)...")

    # base has state_code/dist_code possibly float/int; Year int
    b = base.copy()
    b["state_code"] = b["state_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    b["dist_code"] = b["dist_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    # Unmatched rows may have nan codes
    b.loc[b["state_code"].isin(["nan", "None", "<NA>"]), "state_code"] = pd.NA
    b.loc[b["dist_code"].isin(["nan", "None", "<NA>"]), "dist_code"] = pd.NA
    b["Year"] = b["Year"].astype(int)

    rates = eff_new.loc[
        eff_new.case_category == "all",
        ["state_code", "dist_code", "year", "cases_disposed_in_year",
         "pending_cases_end_prev_year", "disposal_rate_1", "disposal_rate_2"],
    ].copy()
    rates["year"] = rates["year"].astype(int)

    # civil/criminal rates too
    for cat, suf in [("civil", "_civil"), ("criminal", "_criminal")]:
        sub = eff_new.loc[
            eff_new.case_category == cat,
            ["state_code", "dist_code", "year", "cases_disposed_in_year", "disposal_rate_1", "disposal_rate_2"],
        ].rename(columns={
            "cases_disposed_in_year": f"cases_disposed_in_year{suf}",
            "disposal_rate_1": f"disposal_rate_1{suf}",
            "disposal_rate_2": f"disposal_rate_2{suf}",
        })
        rates = rates.merge(sub, on=["state_code", "dist_code", "year"], how="left")

    # drop old rate cols if re-running
    drop_cols = [c for c in b.columns if c.startswith("disposal_rate_") or c.startswith("cases_disposed_in_year") or c == "pending_cases_end_prev_year"]
    b = b.drop(columns=drop_cols, errors="ignore")

    out = b.merge(
        rates,
        left_on=["state_code", "dist_code", "Year"],
        right_on=["state_code", "dist_code", "year"],
        how="left",
        suffixes=("", "_r"),
    )
    if "year_r" in out.columns:
        out = out.drop(columns=["year_r"])

    csv_out = OUT_DIR / "district_year_with_efficiency.csv"
    dta_out = OUT_DIR / "district_year_with_efficiency.dta"
    out.to_csv(csv_out, index=False)

    dta = out.copy()
    for c in dta.select_dtypes(include="object").columns:
        dta[c] = dta[c].astype(str).where(dta[c].notna(), None)
    rename = {c: c[:32] for c in dta.columns if len(c) > 32}
    dta = dta.rename(columns=rename)
    dta.to_stata(dta_out, write_index=False, version=118)

    # Copy to Downloads for easy email
    for src in [
        OUT_DIR / "district_year_efficiency_with_disposal_rates.csv",
        csv_out,
        dta_out,
    ]:
        dest = DOWNLOADS / src.name
        dest.write_bytes(src.read_bytes())
        print(f"Copied to {dest}")

    matched = out["disposal_rate_1"].notna().sum()
    print(f"Shivangi rows with disposal_rate_1: {matched}/{len(out)}")


if __name__ == "__main__":
    main()
