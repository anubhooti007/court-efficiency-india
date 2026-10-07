# District-year file with court-efficiency merge

## For Shivangi

**Main file to use:** `district_year_with_efficiency.dta`  
(also CSV: `district_year_with_efficiency.csv`)

Your skeleton (`regddname`, `regdstate`, `Year`) is preserved as the left side.
Court-efficiency variables from the DDL district-court panel are merged on.

### Merge keys
- District/state names matched via a cleaned name crosswalk (Census-style names in your file → DDL/eCourts names).
- `Year` (your file) ↔ `year` (efficiency panel). The efficiency file used here is the **calendar-year** vintage (`year` = 2010…2018).

### Match rates
| Year | Your rows | Matched to efficiency | Match % |
|------|-----------|------------------------|---------|
| 2013–2017 | all | all | **100%** |
| 2018 | 303 | 302 | **99.7%** |
| 2019–2020 | all | 0 | **0%** (DDL judicial microdata ends Dec 2018) |

Only unmatched district name in your list: **Gujarat / Gujarat** (looks like a state-level placeholder, not a real district).

### Key columns added
- `state_code`, `dist_code`, `district_name`, `state_name` — DDL identifiers used for the match  
- `match_type` — `exact_norm` / `fuzzy_contain` / `manual_map` / `unmatched`  
- `efficiency_matched` — 1 if `court_efficiency_index_simple` is non-missing  
- **All-cases metrics:** `cases_filed`, `cases_disposed`, `clearance_rate`, `same_year_disposal_share`, duration percentiles, pending shares, z-scores, `court_efficiency_index_simple`, `court_efficiency_index_full`  
- **Civil / criminal extras:** `*_civil`, `*_criminal` for the index, clearance, median days, pending share  

### Supporting files
- `name_crosswalk.csv` — every unique district in your file and the DDL name it mapped to  
- `unmatched_districts.csv` — districts that did not map  
- `merge_match_report.csv` — counts by year × match status  
- `merge_efficiency_into_district_year.py` — reproducible merge script  

### Note for analysis
For 2019–2020 rows, efficiency fields are missing by construction. Either drop those years for court-efficiency analysis, or carry forward / leave as missing and flag with `efficiency_matched == 0`.
