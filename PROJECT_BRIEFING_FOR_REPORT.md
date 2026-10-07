# DETAILED PROJECT BRIEFING — District-Level Court Efficiency Dataset
## For Master’s Thesis / Research Report Generation
## Author of the work: Anubhooti Jain (BITS Pilani Goa)
## Last updated: September 2026

---

# 1. PROJECT IDENTITY AND PURPOSE

## 1.1 Who
- **Student / builder of the dataset:** Anubhooti Jain  
  - Dual degree: B.Eng. Electrical & Electronics + MSc Economics, BITS Pilani Goa Campus  
  - Email: f20221128@goa.bits-pilani.ac.in  
  - This work is toward a **Master’s Thesis** (degree requirement at BITS), done in collaboration with faculty.

- **Faculty / research team:**
  - **Prof. Bhavya Singhvi** — Associate Professor, IIM Udaipur (project lead / connector)  
  - **Prof. Maya Ganesh** — Production and Operations Management, IIM Bangalore  
  - **Prof. Shivangi Agarwal** — Finance Area (Goa Institute of Management / IIMU PhD affiliation in email)

## 1.2 Broader research theme
The collaboration is about the **Indian corporate bankruptcy / insolvency resolution landscape (IBC and related institutional environment)** and how it affects constituents (creditors, firms, etc.).

One concrete empirical input needed for the research is a measure of **how efficiently district / lower courts work**, at the **district × year** level, because court delay and backlog can affect bankruptcy outcomes, recovery, and firm behavior.

## 1.3 Anubhooti’s concrete deliverable
Anubhooti designed and built an end-to-end data pipeline that converts the public **DevDataLab (DDL) Indian Judicial Microdata** (~81 million lower-court cases, filing years 2010–2018) into a clean, analysis-ready **district-level court-efficiency panel**, with:
- separate rows for **all / civil / criminal** cases,
- volume, speed, clearance, pendency metrics,
- standardized scores,
- composite efficiency indices,
- full documentation and a reproducible Python script,
- later a **financial-year (FY)** version of the panel,
- and a merge of that efficiency data into Prof. Shivangi’s district–year skeleton for her main analysis sample.

**Anubhooti is the author of the dataset construction.** Supporting tools (Cursor/ChatGPT) were used only for verification, documentation drafting, ASI exploration notes, and the final name-matching merge helper—not for originating the research design or the core pipeline logic.

---

# 2. EMAIL / PROJECT TIMELINE (FROM THE “INTRODUCTION” THREAD)

| Date | Event |
|------|--------|
| 4 Jul 2026 | Prof. Bhavya introduces Anubhooti to Profs. Maya and Shivangi; frames work around corporate bankruptcy resolution and Indian institutional landscape. |
| 5 Jul 2026 | Anubhooti welcomes the opportunity. |
| 12 Jul 2026 | Anubhooti shares the **first version** of the district court efficiency dataset (calendar-year vintage) with all output CSVs. |
| 14 Jul 2026 | Shivangi thanks her; asks for (a) a step-by-step replication document from case-level data to district-year panel, and (b) exact definitions of efficiency variables. |
| 15 Jul 2026 | Anubhooti sends `replication_guide.md` + `build_district_court_efficiency.py`. |
| 16–21 Jul 2026 | Meeting scheduled; Zoom walkthrough of the data. |
| 23 Jul 2026 | Anubhooti re-sends outputs **reorganized by Indian financial year (April–March)** instead of calendar year, plus a more heavily commented script. |
| 27 Jul 2026 | Shivangi asks clarifying questions on clearance rate, z-scores, and the simple efficiency index; cannot open `.py` and asks for another format; assigns **ASI (Annual Survey of Industries)** exploration as next task. |
| 29 Jul 2026 | Anubhooti answers the three questions in detail; attaches script as `.txt`; says she has begun exploring ASI. |
| 1 Sep & 9 Sep 2026 | Shivangi follows up specifically on **Point 2 (clearance rate)**; wants a short call to finalize court-efficiency. |
| 10 Sep 2026 | Call held. Shivangi shares `District_year_data.dta` — unique district–year pairs from her sample — and asks Anubhooti to **merge court-efficiency into that file** so she can merge into her main analysis sample. |
| 22 Sep 2026 | Prof. Bhavya asks for updates. |
| 23 Sep 2026 | Anubhooti sends `district_year_with_efficiency.dta/.csv` and clarifies clearance-rate construction after the call (cohort eventual disposal, not period clearance). |

---

# 3. DATA SOURCE

## 3.1 Primary source
- **DevDataLab (DDL) / Development Data Lab — Indian Judicial Data**  
- URL: https://www.devdatalab.org/judicial-data  
- Underlying scrape: Indian e-Courts platform (district / lower judiciary)  
- Coverage used: cases with filing dates from **1 Jan 2010 to 31 Dec 2018**  
- Scale: about **80.9 million** case rows across yearly files; about **76.8 million** rows in acts/sections  

## 3.2 Academic citation (DDL paper underlying the public data)
Ash, Asher, Bhowmick, Bhupatiraju, Chen, Devi, Goessmann, Novosad, Siddiqi (2025), “In-Group Bias in the Indian Judiciary: Evidence from 5 Million Criminal Cases,” *Review of Economics and Statistics*.

## 3.3 Raw inputs Anubhooti used
Under a local project folder historically called `IBC/csv/`:

1. **Case files (calendar-year on disk):**  
   `cases/cases_2010.csv` … `cases/cases_2018.csv`  
   (~81M rows total)

2. **Acts / sections:**  
   `acts_sections.csv` (~3.6 GB, ~77M rows) — used mainly for the criminal flag

3. **Key / mapping files:**  
   state, district, court, type_name, purpose_name, disp_name, act, section keys

4. **Deliberately ignored:**  
   judge files (`judges_clean`, `judge_case_merge_key`) — because the goal is **court/district efficiency**, not judge-level analysis, and judge matching in DDL is incomplete.

## 3.4 Columns kept from each case file
`ddl_case_id`, `year`, `state_code`, `dist_code`, `court_no`, `type_name`, `purpose_name`, `disp_name`, `date_of_filing`, `date_of_decision`  
(Optional/future: `date_of_registration` — not present in DDL 2010–18.)

Unused columns included gender flags, listing dates, CINO, judge_position, etc.

---

# 4. WHAT ANUBHOOTI BUILT — HIGH-LEVEL PRODUCT

## 4.1 Main analysis file
**`district_year_efficiency.csv`**

- One row = one **(state_code, dist_code, year-or-FY, case_category)**  
- `case_category` ∈ {`all`, `civil`, `criminal`}  
- Contains volume metrics, speed metrics, throughput metrics, pendency metrics, z-scores, and composite indices  

There were **two vintages** of this file:

### Vintage A — Calendar year (first share, ~12 Jul 2026)
- Time unit: calendar year of filing (`year` = 2010…2018)  
- Variable names like `same_year_disposal_share`, `pending_cases_end_year`  
- ~16,937 rows in the copy later found in Downloads  

### Vintage B — Indian financial year (re-share, ~23 Jul 2026)
- Time unit: Indian FY (April–March)  
- `financial_year` = FY **start year** (e.g. 2010 means FY 2010–11)  
- `financial_year_label` like `"2010-11"`  
- `fy_is_complete` flag  
- Variable names like `same_fy_disposal_share`, `pending_cases_end_fy`  
- ~18,784 rows in the full FY run documented earlier  

**Important for report writers:** Shivangi’s later merge skeleton uses `Year` 2013–2020. The merge Anubhooti delivered on 23 Sep used the **calendar-year efficiency panel** available in Downloads (`year` 2010–2018) matched to Shivangi’s `Year`. The FY rebuild remains the conceptually preferred panel for Indian macro/IBC alignment; any report should state clearly which vintage is used in each analysis step.

## 4.2 Supporting output files (all generated by Anubhooti’s pipeline)
1. `file_inventory.csv` — every input file found, size, columns, guessed role  
2. `decoded_districts_raw.csv` — state × district × year/FY × decoded name × case counts  
3. `decoded_district_code_check.csv` — stability of `state_code + dist_code` across years  
4. `case_type_summary.csv` — case-type codes × criminal flag × counts  
5. `civil_criminal_classification_table.csv` — final civil/criminal label per type + source  
6. `data_quality_summary.csv` — missing dates, extreme durations, classification source shares  
7. `assumptions_and_choices.md` — judgment calls documented  
8. `replication_guide.md` — full replication instructions  
9. (Internal) `walkthrough_script.md` — meeting talking points  

## 4.3 Code artifact
**`build_district_court_efficiency.py`** (~1,500–2,000 lines depending on vintage)  
Also shared as `.txt` when Shivangi could not open `.py`.

Design features:
- Streams huge CSVs in 1M-row chunks  
- Caches intermediates as parquet (`work/per_case_criminal.parquet`, `work/case_min/case_min_YYYY.parquet`)  
- Two-pass design: stream/decode/cache → aggregate/index  
- ~20 minutes end-to-end on a 16 GB machine  

---

# 5. PIPELINE — STEP BY STEP (HOW THE DATASET WAS CONSTRUCTED)

## Step 0 — File inventory
Scan data directory; tag files as case / acts_sections / keys / judge; write `file_inventory.csv`.

## Step 1 — Pre-aggregate acts/sections
Collapse ~77M act-section rows to **one row per `ddl_case_id`**:
- `criminal_any = max(criminal)` → primary civil/criminal signal  
- `criminal_all = min(criminal)`  
- `n_sections = count`  
Cache as parquet for fast joins.

## Step 2 — Stream each yearly case file
For each chunk:
1. Join criminal flag on `ddl_case_id` (pyarrow hash join)  
2. Decode codes → names using key files  
3. Parse dates; treat sentinels (`1970-01-01`, `0000-00-00`, `-9998`, `-9999`) as missing  
4. Derive filing/decision calendar year-month; convert to FY if FY vintage  
5. Set `disposed = 1` iff decision date non-missing; else pending  
6. Compute duration (decision − filing); flag negative and >40-year extremes; exclude those from duration stats only  
7. Classify civil vs criminal  
8. Update accumulators; write minimal per-case parquet  

### Decoding strategy (important)
DDL keys are year-scoped but thinly populated after 2010. Anubhooti used:
1. Join on `year + code(s)` first  
2. Fallback fill from year-agnostic `code(s)` only  

This preserves almost all district names from the 2010 baseline.

### Civil / criminal classification
1. **Primary:** observed `criminal_any` from acts/sections → `classification_source = observed_flag`  
2. **Fallback:** keyword match on decoded `type_name_s` (IPC, CrPC, bail, NDPS, POCSO, civil suit, MACT, etc.) → `fallback_rule`  
3. Else `unknown`  

## Step 3–6 — Diagnostic tables
Emit case-type summary, civil/criminal table, decoded districts, code-stability check, data-quality summary.

### District-code stability finding
Of ~632 unique `state_code + dist_code` pairs, **~630 are name-stable** across years. Only trivial conflicts (e.g. Hoshiarpur typo; Jaipur Metro renaming). Conclusion: **`state_code + dist_code` is a reliable district ID** for merging to external Indian datasets.

## Step 7 — District × time × category aggregation
Load all case_min parquets. Drop rows missing state, district, or filing time. For each category in {all, civil, criminal}, group by district × filing year/FY and compute:
- `cases_filed`  
- `cases_disposed` (see critical definition below)  
- duration mean / median / p75 / p90  
- `clearance_rate`  
- `same_year` or `same_fy` disposal share  

Then compute **pending stock** at end of each year/FY (second pass):
- Pending at end of period y = filed on or before end of y AND not disposed on or before end of y  
- Age in whole years/FYs  
- Old-pending shares >2 and >5 periods  

Derive `active_cases = cases_disposed + pending_cases_end_*` and `pending_share`.

## Step 8 — Efficiency scores and indices
Within each `(time_period × case_category)` group, z-score raw metrics. Flip signs so **higher always = more efficient**:

- `speed_score = −z(median_disposal_days)`  
- `clearance_score = +z(clearance_rate)`  
- `same_year_score` or `same_fy_score = +z(same_*_disposal_share)`  
- `pendency_score = −z(pending_share)`  
- `old_case_score = −z(old_pending_share_2*)`  

Composites:
- **`court_efficiency_index_simple`** = mean of (speed, clearance, same-period scores)  
- **`court_efficiency_index_full`** = mean of all five, only when both pending scores exist  

Interpretation: 0 ≈ average peer district that period/category; +1 ≈ one SD more efficient; −1 ≈ one SD less.

## Step 9 — Assumptions markdown
Auto-write human-readable assumptions document.

---

# 6. CRITICAL VARIABLE DEFINITIONS (MUST GET THESE RIGHT IN ANY REPORT)

## 6.1 Disposed (case level)
`disposed = 1` if and only if `date_of_decision` is non-missing after sanitization.  
(Not based on disposition code text.)

## 6.2 Cases filed (district–period row)
Number of cases in that district and category whose **filing** falls in that calendar year or financial year (depending on vintage).

## 6.3 Cases disposed (district–period row) — CRITICAL
**Grouped by filing cohort, NOT by decision period.**

For a district–FY (or year) row:
- Denominator universe = cases **filed** in that period  
- `cases_disposed` = how many of **those same cases** eventually have a decision date **anywhere in the DDL window** (through Dec 2018)

So for FY 2012–13, `cases_disposed` means:
- ✔ cases filed in FY 2012–13 that were eventually disposed by end of DDL data  
- ✘ NOT “all cases whose disposal date fell in FY 2012–13” (that would include older filings)

## 6.4 Clearance rate
\[
\text{clearance\_rate} = \frac{\text{cases\_disposed}}{\text{cases\_filed}}
\]
Reported as a **ratio in [0, 1]** (0.85 = 85%).  
**Cannot exceed 1** in this implementation, because the numerator is a subset of the filing cohort.

This is **not** the conventional judicial “period clearance rate”:
\[
\frac{\text{all disposals occurring during period } t}{\text{all filings during period } t}
\]
which can exceed 100% when courts clear backlog.

### Why older periods show higher clearance rates
Right-censoring / follow-up length:
- Cases filed in 2010 have ~8 years until Dec 2018 to be observed as disposed  
- Cases filed in 2018 have almost no follow-up  

So older filing cohorts mechanically show higher eventual disposal rates. Anubhooti explained this to Shivangi (Jul 29 and again Sep 23 after their call).

## 6.5 Same-year / same-FY disposal share
Share of the filing cohort that is disposed **in the same** calendar year or financial year (`filing_time == decision_time` and disposed).  
Measures within-period speed; distinct from eventual clearance.

## 6.6 Pending stock
At end of period y (31 Dec for calendar vintage; 31 Mar for FY vintage):
- filed on/before end of y  
- and not disposed on/before end of y  

**Limitation:** DDL has no cases filed before 2010, so there is **no true pre-2010 opening stock**. Early-period pendency is understated relative to the real world. Old-pending shares (especially 5-year) are distorted early in the panel.

## 6.7 Duration
Days between filing and decision, only for disposed cases with duration in [0, 40 years].  
`date_of_registration` unavailable in DDL 2010–18.

## 6.8 Financial-year conversion (FY vintage)
Indian FY = 1 April → 31 March.  
Rule: if month ∈ {Jan, Feb, Mar} → FY start = calendar_year − 1; else FY start = calendar_year.  
Example: filed 14 Feb 2011 → FY 2010–11; filed 1 May 2011 → FY 2011–12.

Complete FYs in DDL cut: FY 2010–11 through FY 2017–18 (`fy_is_complete = 1`).  
Partial edges: FY 2009–10 (only Jan–Mar 2010) and FY 2018–19 (only Apr–Dec 2018).

---

# 7. MERGE INTO SHIVANGI’S MAIN-SAMPLE SKELETON (SEP 2026)

## 7.1 What Shivangi sent
`District_year_data.dta`:
- Columns: `regddname` (district name), `regdstate` (state name), `Year`  
- 2,306 rows  
- 324 unique district–state pairs  
- 20 states  
- Years: **2013–2020**  

These are the district–years present in her analysis sample; she needed efficiency variables attached so she can merge into her main firm/case sample.

## 7.2 What Anubhooti delivered (23 Sep 2026)
`district_year_with_efficiency.dta` and `.csv`:
- Left side = Shivangi’s skeleton unchanged  
- Right side = efficiency metrics (all-cases primary + selected civil/criminal columns)  
- Plus match metadata: `state_code`, `dist_code`, DDL names, `match_type`, `efficiency_matched`  

## 7.3 How matching worked
Shivangi uses Census-style names (e.g. Ahmadabad, Sonipat, Kolkata, NCT of Delhi).  
DDL uses eCourts names (e.g. Ahmedabad, Sonepat, Calcutta, Delhi).  

Anubhooti built a name crosswalk:
- normalized string matching  
- manual map for known Census↔DDL renames (Anantapur→Ananthapur, Bid→Beed, Kolkata→Calcutta, Purba Champaran→Motihari, etc.)  
- fuzzy containment within state as backup  

## 7.4 Match rates
| Year | Match to efficiency |
|------|---------------------|
| 2013–2017 | **100%** |
| 2018 | **99.7%** (only miss: placeholder “Gujarat / Gujarat”) |
| 2019–2020 | **0%** — DDL ends Dec 2018; no court microdata |

Overall 2013–2018 match ≈ **99.94%**.

## 7.5 Variables useful for Shivangi’s regressions
Primary (all-cases):
- `court_efficiency_index_simple`  
- `court_efficiency_index_full`  
- `clearance_rate`  
- `median_disposal_days`  
- `pending_share`  
- optionally `same_year_disposal_share`, duration percentiles, old-pending shares  

Also provided: `_civil` / `_criminal` versions of index, clearance, median days, pending share.

Filter recommendation: `efficiency_matched == 1` for rows with a successful merge.

---

# 8. ASI ASSIGNMENT (NEXT / PARALLEL WORKSTREAM)

On 27 Jul 2026, Shivangi asked Anubhooti to explore:
https://microdata.gov.in/NADA/index.php/catalog/ASI/

**Annual Survey of Industries (ASI)** — MoSPI/NSO microdata on registered manufacturing factories in India.

What was established from public metadata (unit files require free login):
- 52 study rounds, roughly 1974–75 through 2023–24  
- Each modern round = 10 relational “Block” files A–J  
- Unit of analysis = factory  
- Join key within a year = **DSL** (Dispatch Serial) across blocks  
- Block A = identification + multiplier/weight (`MULT` — mandatory for population totals)  
- Blocks C–J = fixed assets, working capital, employment/wages, expenses, receipts, indigenous/imported inputs, products  
- Industry codes: NIC-2008; product codes: NPCMS  
- Repeated cross-section, not a firm panel across years in the public files  

Possible uses linking to the court-efficiency / bankruptcy project: district/state manufacturing structure, employment, GVA, capital intensity as covariates or outcomes alongside court efficiency—**after** downloading unit files with a NADA account and harmonizing geography.

Anubhooti noted she had begun exploring ASI structure; a detailed ASI README was also drafted from the public catalog metadata.

---

# 9. KEY METHODOLOGICAL CHOICES AND LIMITATIONS (FOR REPORT “DISCUSSION”)

## Choices
1. Court-level, not judge-level efficiency  
2. Filing-date based timing (registration date unavailable)  
3. Disposed = presence of decision date  
4. Clearance = eventual disposal of filing cohort (not period clearance)  
5. Civil/criminal via acts flag + keyword fallback, with source tagged  
6. Year-aware decode with year-agnostic fallback  
7. Equal-weight average of z-scores for composite index (transparent; alternatives like PCA possible later)  
8. FY realignment to match Indian institutional/statistical year  

## Limitations
1. **Right-censoring** of clearance for recent cohorts  
2. **No pre-2010 opening pending stock** → early pendency understated  
3. Keyword fallback can misclassify ambiguous case types  
4. Small districts / tribunals can dominate top of rankings (filter by `cases_filed` recommended for inference)  
5. NIC/geography renames complicate long panels and external merges  
6. Public DDL judge match incomplete (intentionally unused)  
7. Efficiency data ends 2018 → Shivangi’s 2019–2020 district-years cannot be filled from this source  
8. Two vintages (calendar vs FY) exist; analyses must not mix them silently  

---

# 10. SUGGESTED STRUCTURE FOR A CHATGPT-GENERATED REPORT

You can ask ChatGPT to produce a report with sections such as:

1. **Title / abstract** — Constructing a district-level court efficiency panel for India using eCourts/DDL data, for research on insolvency/IBC institutions  
2. **Introduction** — Motivation (court delay, bankruptcy resolution, need for district–year efficiency measure); thesis collaboration context  
3. **Data** — DDL judicial microdata description, coverage, scale, ignored judge files  
4. **Construction methodology** — Pipeline steps 0–9; civil/criminal classification; decoding; FY conversion  
5. **Variable dictionary** — Every metric in `district_year_efficiency.csv` with formulas  
6. **Clearance-rate discussion** — Cohort vs period clearance; censoring; comparison to same-FY share  
7. **Validation** — District-code stability; data-quality summaries; match rates to Shivangi’s sample  
8. **Integration with analysis sample** — Name crosswalk; merge results; missing 2019–20  
9. **Limitations and robustness** — Censoring, opening stock, small districts, classification noise  
10. **Next steps** — ASI covariates; possible period-clearance alternative metric; FY-only analysis sample; linking to IBC case outcomes  
11. **Appendix** — File inventory; replication command; email timeline of deliverables  

---

# 11. ONE-PARAGRAPH “AUTHOR CREDIT” BLURB (USE IN REPORT)

Anubhooti Jain independently designed and implemented a reproducible Python pipeline that transforms approximately 81 million Indian lower-court case records from the DevDataLab judicial microdata (2010–2018) into a district–year court-efficiency panel, including civil/criminal splits, pendency reconstruction, standardized scores, and composite efficiency indices. She produced accompanying diagnostics, a replication guide, and both calendar-year and Indian financial-year vintages of the panel; clarified methodological definitions (notably clearance as a filing-cohort eventual disposal rate); and merged the efficiency measures onto the district–year pairs required for the coauthors’ main empirical sample. This work forms part of her Master’s thesis collaboration with faculty at IIM Udaipur, IIM Bangalore, and GIM on the institutional environment surrounding corporate bankruptcy resolution in India.

---

# 12. FILE CHECKLIST (WHAT EXISTS / WHAT TO POINT TO)

**Core construction**
- `build_district_court_efficiency.py` (and `.txt` share)  
- `replication_guide.md`  
- `district_year_efficiency.csv` (calendar and/or FY vintage)  
- Diagnostic CSVs listed in §4.2  

**Merge for Shivangi**
- Input: `District_year_data.dta`  
- Output: `district_year_with_efficiency.dta` / `.csv`  
- Aux: `name_crosswalk.csv`, `unmatched_districts.csv`, `merge_match_report.csv`, `MERGE_NOTE_FOR_SHIVANGI.md`  

**ASI**
- MoSPI NADA catalog link; exploratory README on ASI block structure (public metadata)  

---

# END OF BRIEFING

Use this document as the sole context dump for ChatGPT when asking it to write a formal report, thesis chapter, or project summary. Instruct ChatGPT to treat Anubhooti Jain as the sole author of the dataset construction and to distinguish calendar-year vs financial-year vintages wherever metrics are discussed.
