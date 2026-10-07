"""Merge DDL district-court efficiency into Shivangi's district-year skeleton.

Shivangi file keys: regddname, regdstate, Year (2013-2020)
Efficiency keys:   district_name, state_name, year (2010-2018), case_category

Outputs (written next to this script / to out_dir):
  - district_year_with_efficiency.dta / .csv  (main deliverable)
  - merge_match_report.csv                    (which pairs matched / failed)
  - name_crosswalk.csv                        (district name mapping used)
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

DOWNLOADS = Path(r"C:\Users\anubh\Downloads")
OUT_DIR = Path(r"C:\Users\anubh\OneDrive\Desktop\New folder (3)\ASI")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SHIVANGI = DOWNLOADS / "District_year_data.dta"
EFFICIENCY = DOWNLOADS / "district_year_efficiency.csv"
STATE_KEY = Path(r"C:\ddl_data\csv\keys\cases_state_key.csv")
DIST_KEY = Path(r"C:\ddl_data\csv\keys\cases_district_key.csv")


def norm_name(s: object) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    t = str(s).strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    # common spelling variants
    replacements = {
        "ahmadabad": "ahmedabad",
        "ahmadnagar": "ahmednagar",
        "bengaluru": "bangalore",
        "bengalooru": "bangalore",
        "mysuru": "mysore",
        "mangaluru": "mangalore",
        "belagavi": "belgaum",
        "hubballi": "hubli",
        "tumakuru": "tumkur",
        "vijayapura": "bijapur",
        "kalaburagi": "gulbarga",
        "ballari": "bellary",
        "shivamogga": "shimoga",
        "chikkamagaluru": "chikmagalur",
        "uttara kannada": "uttar kannada",
        "dakshina kannada": "dakshin kannada",
        "gurugram": "gurgaon",
        "gurugaon": "gurgaon",
        "noida": "gautam buddha nagar",
        "gautam budh nagar": "gautam buddha nagar",
        "gautambuddha nagar": "gautam buddha nagar",
        "prayagraj": "allahabad",
        "mumbai suburban": "mumbai suburb",
        "mumbai (suburban)": "mumbai suburb",
        "brihan mumbai": "mumbai",
        "greater mumbai": "mumbai",
        "mumbai city": "mumbai",
        "nct of delhi": "delhi",
        "national capital territory of delhi": "delhi",
        "orissa": "odisha",
        "pondicherry": "puducherry",
        "thiruvananthapuram": "trivandrum",
        "kochi": "ernakulam",
        "kancheepuram": "kanchipuram",
        "kanchipuram": "kanchipuram",
        "tiruchirappalli": "trichy",
        "tiruchirapalli": "trichy",
        "tuticorin": "thoothukudi",
        "thoothukkudi": "thoothukudi",
        "sivagangai": "sivaganga",
        "villupuram": "viluppuram",
        "tirunelveli": "tirunelveli",
        "hoshiarpurr": "hoshiarpur",
        "jaipur metro i": "jaipur metro",
        "jaipur metro": "jaipur metro",
    }
    if t in replacements:
        t = replacements[t]
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # drop trailing tokens like "district", "city"
    t = re.sub(r"\b(district|dist|city|urban|rural|metro)\b", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


STATE_ALIASES = {
    "nct of delhi": "delhi",
    "national capital territory of delhi": "delhi",
    "orissa": "odisha",
    "odisha": "odisha",  # DDL uses Orissa in some rows
}

# Explicit Census/Shivangi district name -> DDL district_name (within state).
# Keys: (norm_state, norm_shivangi_district) -> exact DDL district_name string
MANUAL_DISTRICT_MAP = {
    ("andhra pradesh", "anantapur"): "Ananthapur",
    ("andhra pradesh", "prakasam"): "Prakasham",
    ("andhra pradesh", "visakhapatnam"): "Visakapatnam",
    ("andhra pradesh", "y s r"): "Kadapa",
    ("assam", "sibsagar"): "Sivasagar",
    ("bihar", "purba champaran"): "Motihari",
    ("gujarat", "banas kantha"): "Banaskanth at Palanpur",
    ("gujarat", "panch mahals"): "Panchmahal at Godhra",
    ("gujarat", "sabar kantha"): "Sabarkantha at Himmatnagar",
    ("haryana", "mahendragarh"): "Narnaul",
    ("haryana", "sonipat"): "Sonepat",
    ("jharkhand", "palamu"): "Daltonganj",
    ("jharkhand", "purbi singhbhum"): "East Singhbhum at Jamshedpur",
    ("madhya pradesh", "east nimar"): "Khandwa",
    ("madhya pradesh", "west nimar"): "Mandleshwar",
    ("maharashtra", "bid"): "Beed",
    ("maharashtra", "buldana"): "Buldhana",
    ("maharashtra", "gondiya"): "Gondia",
    ("maharashtra", "raigarh mah"): "Raigad",
    ("odisha", "baleshwar"): "Balasore",
    ("odisha", "jagatsinghapur"): "Jagatsinghpur",
    ("odisha", "kendujhar"): "Keonjhar",
    ("odisha", "khordha"): "Khurda",
    ("rajasthan", "chittaurgarh"): "Chittorgarh",
    ("tamil nadu", "thiruvallur"): "Tiruvallur",
    ("uttar pradesh", "bara banki"): "Barabanki",
    ("uttar pradesh", "kheri"): "Lakhimpur",
    ("uttar pradesh", "rae bareli"): "Raebareli",
    ("uttar pradesh", "sant ravidas nagar"): "Bhadohi SR Nagar",
    ("uttarakhand", "hardwar"): "Haridwar",
    ("west bengal", "barddhaman"): "Purba Bardhaman",
    ("west bengal", "dakshin dinajpur"): "South Dinajpur",
    ("west bengal", "darjiling"): "Darjeeling",
    ("west bengal", "haora"): "Howrah",
    ("west bengal", "hugli"): "Hooghly",
    ("west bengal", "kolkata"): "Calcutta",
    ("west bengal", "north 24 parganas"): "North  Twenty Four Parganas",
    ("west bengal", "paschim medinipur"): "Paschim Medinpur",
    ("west bengal", "south 24 parganas"): "South Twenty Four Parganas",
}


def norm_state(s: object) -> str:
    t = norm_name(s)
    return STATE_ALIASES.get(t, t)


def load_efficiency_with_state() -> pd.DataFrame:
    eff = pd.read_csv(EFFICIENCY)
    # Prefer district key for state_name (year-agnostic fallback: last known)
    dist = pd.read_csv(DIST_KEY, dtype={"state_code": "string", "dist_code": "string"})
    dist["state_code"] = dist["state_code"].astype(str).str.zfill(2)
    dist["dist_code"] = dist["dist_code"].astype(str).str.zfill(2)
    # keep last non-null name per code
    dist_map = (
        dist.dropna(subset=["district_name"])
        .drop_duplicates(["state_code", "dist_code"], keep="last")
        [["state_code", "dist_code", "state_name", "district_name"]]
        .rename(columns={"district_name": "district_name_key", "state_name": "state_name_key"})
    )
    # Also state key for Orissa/Odisha etc.
    st = pd.read_csv(STATE_KEY, dtype={"state_code": "string"})
    st["state_code"] = st["state_code"].astype(str).str.zfill(2)
    st_map = (
        st.dropna(subset=["state_name"])
        .drop_duplicates(["state_code"], keep="last")
        [["state_code", "state_name"]]
        .rename(columns={"state_name": "state_name_from_statekey"})
    )

    eff = eff.copy()
    eff["state_code"] = eff["state_code"].astype(str).str.zfill(2)
    eff["dist_code"] = eff["dist_code"].astype(str).str.zfill(2)
    eff = eff.merge(dist_map, on=["state_code", "dist_code"], how="left")
    eff = eff.merge(st_map, on="state_code", how="left")
    # Prefer key state name; fall back
    eff["state_name"] = eff["state_name_key"].fillna(eff["state_name_from_statekey"])
    # Prefer efficiency's district_name (already decoded); fill from key if missing
    eff["district_name"] = eff["district_name"].fillna(eff["district_name_key"])

    # Harmonize Orissa -> Odisha for matching Shivangi
    eff["state_name_match"] = eff["state_name"].replace({"Orissa": "Odisha"})
    # Delhi naming
    eff.loc[eff["state_name_match"].str.lower() == "delhi", "state_name_match"] = "NCT of Delhi"

    eff["state_norm"] = eff["state_name_match"].map(norm_state)
    # For Odisha, DDL says Orissa — normalize both to odisha
    eff["state_norm"] = eff["state_norm"].replace({"orissa": "odisha"})
    # Delhi
    eff["state_norm"] = eff["state_norm"].replace({"nct of delhi": "delhi", "delhi": "delhi"})

    eff["dist_norm"] = eff["district_name"].map(norm_name)
    return eff


def build_crosswalk(shiv: pd.DataFrame, eff: pd.DataFrame) -> pd.DataFrame:
    """One row per unique Shivangi (state, district) with best DDL match."""
    shiv_pairs = (
        shiv[["regdstate", "regddname"]]
        .drop_duplicates()
        .assign(
            state_norm=lambda d: d["regdstate"].map(norm_state).replace({"nct of delhi": "delhi"}),
            dist_norm=lambda d: d["regddname"].map(norm_name),
        )
    )

    # DDL unique pairs (prefer names that appear most often)
    ddl_pairs = (
        eff.dropna(subset=["district_name", "state_name"])
        .groupby(["state_norm", "dist_norm", "state_code", "dist_code", "state_name", "district_name"], as_index=False)
        .size()
        .sort_values("size", ascending=False)
        .drop_duplicates(["state_norm", "dist_norm"], keep="first")
    )
    # Also index by exact DDL district_name for manual map
    ddl_by_name = (
        eff.dropna(subset=["district_name"])
        .groupby(["state_norm", "district_name"], as_index=False)
        .agg(state_code=("state_code", "first"), dist_code=("dist_code", "first"),
             state_name=("state_name", "first"), size=("district_name", "size"))
        .sort_values("size", ascending=False)
        .drop_duplicates(["state_norm", "district_name"], keep="first")
    )

    # Exact normalized match
    merged = shiv_pairs.merge(
        ddl_pairs,
        on=["state_norm", "dist_norm"],
        how="left",
        suffixes=("", "_ddl"),
    )
    merged["match_type"] = np.where(merged["district_name"].notna(), "exact_norm", "unmatched")

    # Manual Census -> DDL name map
    still = merged["match_type"] == "unmatched"
    for idx in merged.index[still]:
        key = (merged.at[idx, "state_norm"], merged.at[idx, "dist_norm"])
        ddl_name = MANUAL_DISTRICT_MAP.get(key)
        if not ddl_name:
            continue
        sn = merged.at[idx, "state_norm"]
        hit = ddl_by_name[(ddl_by_name.state_norm == sn) & (ddl_by_name.district_name == ddl_name)]
        if hit.empty:
            continue
        row = hit.iloc[0]
        for col in ["state_code", "dist_code", "state_name", "district_name"]:
            merged.at[idx, col] = row[col]
        merged.at[idx, "size"] = row["size"]
        merged.at[idx, "match_type"] = "manual_map"

    # For still unmatched, try district-only containment within same state
    still = merged["match_type"] == "unmatched"
    if still.any():
        by_state = {
            sn: g.set_index("dist_norm")
            for sn, g in ddl_pairs.groupby("state_norm")
        }
        for idx in merged.index[still]:
            sn = merged.at[idx, "state_norm"]
            dn = merged.at[idx, "dist_norm"]
            cand = by_state.get(sn)
            if cand is None or cand.empty:
                continue
            hits = []
            for ddl_dn, row in cand.iterrows():
                if not ddl_dn or not dn:
                    continue
                if dn in ddl_dn or ddl_dn in dn:
                    hits.append((abs(len(dn) - len(ddl_dn)), row))
            if hits:
                hits.sort(key=lambda x: x[0])
                row = hits[0][1]
                for col in ["state_code", "dist_code", "state_name", "district_name", "size"]:
                    merged.at[idx, col] = row[col]
                merged.at[idx, "match_type"] = "fuzzy_contain"

    return merged


def main() -> None:
    shiv = pd.read_stata(SHIVANGI)
    shiv["Year"] = shiv["Year"].astype(int)
    print(f"Shivangi skeleton: {shiv.shape[0]} rows, "
          f"{shiv.groupby(['regdstate','regddname']).ngroups} district-state pairs, "
          f"years {sorted(shiv.Year.unique())}")

    eff = load_efficiency_with_state()
    print(f"Efficiency panel: {eff.shape[0]} rows, years {sorted(eff.year.unique())}, "
          f"categories {sorted(eff.case_category.unique())}")

    crosswalk = build_crosswalk(shiv, eff)
    crosswalk_path = OUT_DIR / "name_crosswalk.csv"
    crosswalk.to_csv(crosswalk_path, index=False)
    n_exact = (crosswalk.match_type == "exact_norm").sum()
    n_fuzzy = (crosswalk.match_type == "fuzzy_contain").sum()
    n_miss = (crosswalk.match_type == "unmatched").sum()
    print(f"Crosswalk: {n_exact} exact, {n_fuzzy} fuzzy, {n_miss} unmatched "
          f"(of {len(crosswalk)} unique district-state pairs)")

    # Attach codes onto shivangi rows
    shiv2 = shiv.merge(
        crosswalk[["regdstate", "regddname", "state_code", "dist_code", "state_name",
                   "district_name", "match_type"]],
        on=["regdstate", "regddname"],
        how="left",
    )

    # Efficiency metrics to bring over — keep case_category=all as wide defaults,
    # plus civil/criminal index columns for convenience.
    metric_cols = [
        "cases_filed", "cases_disposed", "mean_disposal_days", "median_disposal_days",
        "p75_disposal_days", "p90_disposal_days", "clearance_rate",
        "same_year_disposal_share", "pending_cases_end_year", "old_pending_share_2yr",
        "old_pending_share_5yr", "active_cases", "pending_share",
        "speed_score", "clearance_score", "same_year_score", "pendency_score",
        "old_case_score", "court_efficiency_index_simple", "court_efficiency_index_full",
    ]

    def pivot_cat(cat: str, suffix: str) -> pd.DataFrame:
        sub = eff.loc[eff.case_category == cat, ["state_code", "dist_code", "year"] + metric_cols].copy()
        rename = {c: f"{c}{suffix}" for c in metric_cols}
        # For 'all', keep unsuffixed names as the primary for Shivangi
        if suffix == "":
            return sub
        return sub.rename(columns=rename)

    all_m = pivot_cat("all", "")
    civ_m = pivot_cat("civil", "_civil")
    cri_m = pivot_cat("criminal", "_criminal")
    # Only bring index + a few key metrics for civil/criminal to limit width
    civ_keep = ["state_code", "dist_code", "year",
                "court_efficiency_index_simple_civil", "court_efficiency_index_full_civil",
                "clearance_rate_civil", "median_disposal_days_civil", "pending_share_civil"]
    cri_keep = ["state_code", "dist_code", "year",
                "court_efficiency_index_simple_criminal", "court_efficiency_index_full_criminal",
                "clearance_rate_criminal", "median_disposal_days_criminal", "pending_share_criminal"]
    civ_m = civ_m[[c for c in civ_keep if c in civ_m.columns]]
    cri_m = cri_m[[c for c in cri_keep if c in cri_m.columns]]

    # Merge year: Shivangi Year <-> efficiency year (calendar years in this file)
    out = shiv2.merge(
        all_m,
        left_on=["state_code", "dist_code", "Year"],
        right_on=["state_code", "dist_code", "year"],
        how="left",
    )
    out = out.merge(civ_m, on=["state_code", "dist_code", "year"], how="left")
    out = out.merge(cri_m, on=["state_code", "dist_code", "year"], how="left")

    # Flags
    out["efficiency_matched"] = out["court_efficiency_index_simple"].notna().astype(int)
    out["year_in_ddl_range"] = out["Year"].between(2010, 2018).astype(int)

    # Match report
    report = (
        out.groupby(["Year", "efficiency_matched", "match_type"], dropna=False)
        .size()
        .reset_index(name="n_rows")
        .sort_values(["Year", "efficiency_matched", "match_type"])
    )
    report_path = OUT_DIR / "merge_match_report.csv"
    report.to_csv(report_path, index=False)

    unmatched_districts = crosswalk.loc[crosswalk.match_type == "unmatched",
                                        ["regdstate", "regddname"]].sort_values(["regdstate", "regddname"])
    unmatched_path = OUT_DIR / "unmatched_districts.csv"
    unmatched_districts.to_csv(unmatched_path, index=False)

    # Column order: skeleton first, then ids, then all-category metrics, then civil/criminal
    front = ["regddname", "regdstate", "Year", "state_code", "dist_code",
             "district_name", "state_name", "match_type", "efficiency_matched", "year_in_ddl_range"]
    rest = [c for c in out.columns if c not in front and c != "year"]
    out = out[front + (["year"] if "year" in out.columns else []) + rest]

    csv_path = OUT_DIR / "district_year_with_efficiency.csv"
    dta_path = OUT_DIR / "district_year_with_efficiency.dta"
    out.to_csv(csv_path, index=False)

    # Stata: truncate long strings if needed; convert categoricals
    dta = out.copy()
    for c in dta.select_dtypes(include="object").columns:
        dta[c] = dta[c].astype(str).where(dta[c].notna(), None)
    # Stata variable names max 32 chars
    rename_stata = {}
    for c in dta.columns:
        if len(c) > 32:
            rename_stata[c] = c[:32]
    dta = dta.rename(columns=rename_stata)
    dta.to_stata(dta_path, write_index=False, version=118)

    # Summary
    print("\n=== MERGE SUMMARY ===")
    print(f"Output rows: {len(out)} (should equal Shivangi {len(shiv)})")
    print(f"Matched with efficiency index (all): {out.efficiency_matched.sum()} "
          f"({100*out.efficiency_matched.mean():.1f}%)")
    print("By year:")
    print(
        out.groupby("Year")
        .agg(n=("regddname", "size"), matched=("efficiency_matched", "sum"))
        .assign(match_pct=lambda d: (100 * d.matched / d.n).round(1))
        .to_string()
    )
    print(f"\nWrote:\n  {csv_path}\n  {dta_path}\n  {crosswalk_path}\n  {report_path}\n  {unmatched_path}")
    if n_miss:
        print(f"\nUnmatched districts ({n_miss}) saved to {unmatched_path}")
        print(unmatched_districts.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
