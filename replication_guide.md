# District-Level Court Efficiency Dataset — Replication Guide

**Source data:** DevDataLab / DDL Judicial Data
(<https://www.devdatalab.org/judicial-data>), covering Indian district and
lower court cases filed between **2010 and 2018**.

**Main script:** `build_district_court_efficiency.py`

**Command used:**

```bash
python3 build_district_court_efficiency.py \
    --data-dir IBC/csv \
    --out-dir  IBC/outputs \
    --work-dir IBC/work \
    --chunksize 1000000
```

Total runtime: ~20 minutes end-to-end on a 16 GB Mac.

---

## 1. Input files used

All inputs live under `IBC/csv/` after unpacking the tar.gz archives shipped
by DDL.

### 1.1 Case files (yearly)

Path: `IBC/csv/cases/cases_YYYY.csv` for YYYY = 2010 … 2018.

Total: **80,935,944 case-level rows**.

Columns kept from each case file:

| Column | Purpose |
|---|---|
| `ddl_case_id` | primary key; used to join to acts_sections |
| `year` | filing year |
| `state_code`, `dist_code`, `court_no` | location identifiers (2-char strings, zero-padded) |
| `type_name`, `purpose_name`, `disp_name` | case type / purpose / disposition codes |
| `date_of_filing` | filing date |
| `date_of_decision` | decision date (null if pending) |

Columns present in the raw files but **not used** for this build:
`cino, judge_position, female_defendant, female_petitioner, female_adv_def,
female_adv_pet, date_first_list, date_last_list, date_next_list`.
`date_of_registration` is **not present** in the DDL 2010–18 release.

### 1.2 Acts / sections file

Path: `IBC/csv/acts_sections.csv`. Size: 3.6 GB / **76,811,357 rows**.

Columns: `ddl_case_id, act, section, bailable_ipc, number_sections_ipc,
criminal`.

Only `ddl_case_id` and `criminal` are used for this build.

### 1.3 Key / mapping files

All under `IBC/csv/keys/`:

| File | Purpose | Join keys used |
|---|---|---|
| `cases_state_key.csv` | state_code → state_name | year + state_code |
| `cases_district_key.csv` | (state, dist) → district_name | year + state_code + dist_code |
| `cases_court_key.csv` | (state, dist, court) → court_name | year + state_code + dist_code + court_no |
| `type_name_key.csv` | type_name code → type_name_s | year + type_name |
| `purpose_name_key.csv` | purpose_name code → purpose_name_s | year + purpose_name |
| `disp_name_key.csv` | disp_name code → disp_name_s | year + disp_name |
| `act_key.csv` | act code → act_s | act |
| `section_key.csv` | section code → section_s | section |

For every year-scoped key we run a **two-step merge**: first on
`year + code(s)`, then a **year-agnostic fallback** on `code(s)` alone for
rows that still have no match. This matters most for the district key,
which has 625 rows for 2010, 4 for 2011, 2 for 2014, 1 for 2017 — a strict
year-only merge would leave most 2011–18 rows with a missing district name.

### 1.4 Files deliberately ignored

- `IBC/csv/judges_clean.tar.gz`
- `IBC/csv/keys/judge_case_merge_key.csv`

Reason: judge matching is incomplete in DDL and is only relevant for
judge-level (not district-level) analysis, so it adds noise without value
here.

---

## 2. Step-by-step build pipeline

### Step 0 — Discover files

Recursively scan `--data-dir`, list every `.csv/.csv.gz/.dta/.parquet`, and
tag each with a role (case file, acts_sections, state key, etc.). Judge
files are tagged and then dropped from all subsequent steps.

**Output:** `outputs/file_inventory.csv` (19 files).

### Step 1 — Pre-aggregate acts / sections

The acts_sections file has multiple rows per case (one per act × section).
Stream it in chunks of 1 M rows, groupby `ddl_case_id`, and compute:

- `criminal_any = max(criminal)` — 1 if any row for the case is criminal
- `criminal_all = min(criminal)` — 1 only if every row is criminal
- `n_sections = count(*)` per case

The result is written to `IBC/work/per_case_criminal.parquet`
(76,811,357 unique case IDs, ~900 MB).

We use `criminal_any` as the case-level criminal flag in the rest of the
pipeline.

### Step 2 — Stream the case files

For each of the 9 yearly case CSVs, chunk-read (1 M rows at a time). For
each chunk:

1. **Attach `criminal_any`** via a pyarrow hash join against
   `per_case_criminal.parquet`. Cases that have no acts_sections row get
   `criminal_any = NaN` and are tagged with `act_section_missing = 1`.
2. **Decode codes into labels** using the key files (year-first with
   year-agnostic fallback). Produces `state_name, district_name,
   court_name, type_name_s, purpose_name_s, disp_name_s`.
3. **Parse dates** — `date_of_filing`, `date_of_decision`. DDL sentinel
   values (`1970-01-01`, `0000-00-00`, empty string) are replaced with NaT.
4. **Derive case-level fields**:
   - `filing_year = year(date_of_filing)`
   - `decision_year = year(date_of_decision)`
   - `disposed = 1` if `date_of_decision` is present, else `0`
   - `pending = 1 - disposed`
   - Raw duration = `date_of_decision - date_of_filing` in days.
   - `duration_negative = 1` if raw duration < 0.
   - `duration_extreme = 1` if raw duration > 40 × 365 days.
   - `case_duration_days` = raw duration where 0 ≤ raw ≤ 14 600, else null.
5. **Classify civil vs criminal**:
   - If `criminal_any = 1` → `civil_criminal = criminal`
     (`classification_source = observed_flag`).
   - Else if `criminal_any = 0` → `civil_criminal = civil`
     (`observed_flag`).
   - Else fallback: keyword-match `type_name_s` against lists of criminal
     terms (IPC, CrPC, sessions, FIR, police, bail, NDPS, POCSO, excise,
     corruption, arms act, N.I. Act, etc.) and civil terms (civil suit,
     money suit, execution, MACT, matrimonial, land, rent, arbitration,
     probate, succession, consumer, commercial, etc.). Tag with
     `classification_source = fallback_rule`.
   - If neither rule matches → `civil_criminal = unknown`
     (`classification_source = unknown`).
6. **Update running accumulators** for the case-type summary and the
   per-year data-quality counters.
7. **Write a minimal per-case parquet** to `IBC/work/case_min/case_min_YYYY.parquet`
   with columns `state_code, dist_code, district_name, year, filing_year,
   decision_year, disposed, case_duration_days, civil_criminal`. This
   cache lets Steps 3 and 4 run in one vectorised pass without re-reading
   the raw CSVs.

### Step 3 — Build the case-type summary

From the running accumulator (Step 2), emit:

- `case_type_summary.csv` — one row per `(type_code, type_name_s,
  criminal_flag_observed)` with `count` and `share`.
- `civil_criminal_classification_table.csv` — collapsed by
  `(type_code, type_name_s)` with `n_criminal_flag_1, n_criminal_flag_0,
  n_criminal_flag_missing, final_classification, classification_source,
  share_of_total_cases`. Type-level final classification takes majority
  vote among cases with observed flag, else falls back to keyword rule.

### Step 4 — Decoded district audit

Emit:

- `decoded_districts_raw.csv` — one row per `(state_code, dist_code, year,
  district_name)` with `n_cases`.
- `decoded_district_code_check.csv` — one row per `(state_code, dist_code)`
  with `first_year, last_year, n_years_with_name, n_years_missing_name,
  n_unique_actual_names, district_names_seen, stable_code_flag,
  full_year_coverage_flag`.

Findings: 630 / 632 codes are name-stable, 2 have trivial typos.

### Step 5 — Data-quality summary

Emit `data_quality_summary.csv` — one row per year with counts of missing
dates, negative / extreme durations, missing state / district codes, cases
missing an acts_sections row, and the split of classification sources.

### Step 6 — Second pass: aggregate to district × year × category

Load all `IBC/work/case_min/case_min_YYYY.parquet` files into one pandas
DataFrame (~2.5 GB in memory, ~81 M rows). Drop rows with missing
`state_code`, `dist_code`, or `year`, then loop over
`case_category ∈ {all, civil, criminal}`:

- `all` → every case.
- `civil` → rows with `civil_criminal = civil`.
- `criminal` → rows with `civil_criminal = criminal`.

For each `(state_code, dist_code, district_name, year, case_category)`
group compute the volume, duration, clearance and same-year metrics
defined in Section 3 below.

### Step 7 — Pending stock (cross-year second pass)

For every year `y ∈ [2010, 2018]` and every district-category:

- A case is **pending at end of year `y`** iff
  `filing_year ≤ y` AND (`decision_year > y` OR `decision_year` is null).
- `case_age_years = y - filing_year`.
- `pending_older_2yr = sum(case_age_years > 2)`.
- `pending_older_5yr = sum(case_age_years > 5)`.

### Step 8 — Compose efficiency scores and indices

Within each `(year, case_category)` group, standardise the raw metrics
into z-scores (see Section 3.4 for exact formulas), then average them to
form the composite indices.

### Step 9 — Write assumptions markdown

Emit `assumptions_and_choices.md` documenting every judgment call.

---

## 3. Definitions of every variable in `district_year_efficiency.csv`

The file has **16,937 rows** = ~630 districts × 9 years × 3 case
categories, and 25 columns. Each row is uniquely identified by
`(state_code, dist_code, year, case_category)`.

### 3.1 Identifiers

| Variable | Description |
|---|---|
| `state_code` | 2-char zero-padded DDL state code |
| `dist_code` | 2-char zero-padded DDL district code |
| `district_name` | decoded district name (from `cases_district_key.csv`) |
| `year` | filing year of the cases in this row (2010–2018) |
| `case_category` | one of `all` / `civil` / `criminal` (see Step 2 rule 5) |

### 3.2 Volume metrics

| Variable | Definition |
|---|---|
| `cases_filed` | number of cases with this `(state, dist, year, category)`, i.e. cases filed in that district-year with that category label |
| `cases_disposed` | subset of `cases_filed` for which `date_of_decision` is present (i.e. `disposed = 1`) |
| `pending_cases_end_year` | number of cases with `filing_year ≤ year` AND (`decision_year > year` OR `decision_year` is null), for the same district and category |
| `active_cases` | `cases_disposed + pending_cases_end_year` (null if 0) |

### 3.3 Duration and throughput metrics

All duration figures are computed from
`case_duration_days = date_of_decision - date_of_filing`, restricted to
disposed cases with `0 ≤ duration ≤ 14 600` days (impossible / extreme
durations are dropped).

| Variable | Definition |
|---|---|
| `mean_disposal_days` | mean of `case_duration_days` within the group |
| `median_disposal_days` | 50th percentile of `case_duration_days` within the group (exact, computed via `pandas.groupby(...).quantile(0.5)`) |
| `p75_disposal_days` | 75th percentile of `case_duration_days` |
| `p90_disposal_days` | 90th percentile of `case_duration_days` |
| `clearance_rate` | `cases_disposed / cases_filed`. Interpretation: fraction of filings that are already disposed. Value in [0, 1]; higher is better |
| `same_year_disposal_share` | share of `cases_filed` that were also disposed in the same calendar year (`year == decision_year AND disposed = 1`) divided by `cases_filed`. Higher is better |
| `pending_share` | `pending_cases_end_year / active_cases`. Fraction of the district's active caseload still pending at year-end. Lower is better |
| `old_pending_share_2yr` | share of the pending stock at year-end whose case age (`year - filing_year`) exceeds 2 years. Lower is better |
| `old_pending_share_5yr` | share of the pending stock at year-end whose case age exceeds 5 years. Lower is better |

### 3.4 Standardised scores

For each raw metric, we compute a z-score **within `(year, case_category)`**,
i.e. every district's score is relative to the mean and standard deviation
of all districts observed in that same year and category. This lets the
scores be comparable across years without being distorted by year-level
trends.

Let `x_{d,y,c}` be the raw metric for district `d`, year `y`, category
`c`, and let `μ_{y,c}, σ_{y,c}` be the mean and (population) standard
deviation across all districts within that `(y, c)` cell. Then
`z(x) = (x − μ_{y,c}) / σ_{y,c}` when `σ > 0`, else `NaN`.

We flip the sign of z-scores where **lower is better** so that in every
score higher = more efficient:

| Score variable | Formula |
|---|---|
| `speed_score` | `− z(median_disposal_days)` |
| `clearance_score` | `+ z(clearance_rate)` |
| `same_year_score` | `+ z(same_year_disposal_share)` |
| `pendency_score` | `− z(pending_share)` |
| `old_case_score` | `− z(old_pending_share_2yr)` |

### 3.5 Composite efficiency indices

Both are simple arithmetic means of the standardised scores, computed
row-wise with NaN skipped. Higher = more efficient.

| Index | Definition |
|---|---|
| `court_efficiency_index_simple` | `mean(speed_score, clearance_score, same_year_score)` |
| `court_efficiency_index_full` | `mean(speed_score, clearance_score, same_year_score, pendency_score, old_case_score)`, computed only for rows where both `pendency_score` and `old_case_score` are non-null |

Interpretation: an index of 0 corresponds to an "average" district in that
year and category. A district with `index = +1` is roughly one standard
deviation more efficient than the year-category mean; `-1` is roughly one
standard deviation less efficient.

---

## 4. Intermediate artefacts (regenerated on every run)

These live in `IBC/work/` and are safe to delete once you have the outputs.
A re-run regenerates them; the pipeline reuses them when they already exist.

| File | Contents |
|---|---|
| `work/per_case_criminal.parquet` | one row per `ddl_case_id` with `criminal_any, criminal_all, n_sections` — the collapsed acts_sections file |
| `work/case_min/case_min_YYYY.parquet` (×9) | minimal per-case fields for year YYYY, used by the vectorised aggregation pass |

---

## 5. How to re-run from scratch

```bash
# From IBC/
python3 build_district_court_efficiency.py \
    --data-dir csv \
    --out-dir  outputs \
    --work-dir work \
    --chunksize 1000000
```

Optional flags:

| Flag | Effect |
|---|---|
| `--force-refresh-acts` | re-scan `acts_sections.csv` even if the cache exists |
| `--skip-pending` | skip the cross-year pending-stock second pass (faster; leaves `court_efficiency_index_full` null) |
| `--verbose` | DEBUG logging |

If you delete `IBC/work/` and rerun, the full pipeline reproduces every
output file byte-for-byte (subject to floating-point mean/std ordering,
which is stable in pandas ≥ 2.0).

---

## 6. Where to find things

```
IBC/
├── build_district_court_efficiency.py         # main pipeline
├── csv/                                       # raw DDL data (unpacked)
│   ├── acts_sections.csv
│   ├── cases/cases_YYYY.csv                   # 2010–2018
│   └── keys/*.csv                             # 8 key files (judge key ignored)
├── work/                                      # intermediate parquet caches
│   ├── per_case_criminal.parquet
│   └── case_min/case_min_YYYY.parquet
└── outputs/                                   # final deliverables
    ├── file_inventory.csv
    ├── decoded_districts_raw.csv
    ├── decoded_district_code_check.csv
    ├── case_type_summary.csv
    ├── civil_criminal_classification_table.csv
    ├── data_quality_summary.csv
    ├── district_year_efficiency.csv           # main deliverable
    ├── assumptions_and_choices.md             # methodological choices
    └── replication_guide.md                   # this document
```
