# Disposal Rate variables (added Oct 2026)

Added to `district_year_efficiency_with_disposal_rates.csv` and to the merged Shivangi file.

## Definitions (period-based — NOT the old clearance_rate)

**Disposal Rate 1** (`disposal_rate_1`)
= Cases disposed in year t / New cases filed in year t

- Numerator: cases whose **decision date** falls in calendar year t (in that district × category)
- Denominator: cases whose **filing date** falls in calendar year t (`cases_filed`)
- Can exceed 1 when courts clear backlog (more disposals than new filings)

**Disposal Rate 2** (`disposal_rate_2`)
= Cases disposed in year t / (Pending cases at end of year t−1 + New cases filed in year t)

- Numerator: same period disposals as Rate 1
- Denominator: opening pending stock + new filings (workload)
- Missing for 2010 (no t−1 pending observed in DDL)
- Bounded ≤ 1 within the observed sample

Also added helper columns: `cases_disposed_in_year`, `pending_cases_end_prev_year`.

## Contrast with existing `clearance_rate`
`clearance_rate` = share of the **filing cohort** of year t that is eventually disposed by Dec 2018 (cohort eventual disposal). Different concept from Disposal Rate 1/2.

## Files to use
- Full panel: `district_year_efficiency_with_disposal_rates.csv`
- Shivangi merge: `district_year_with_efficiency.dta` / `.csv` (includes `disposal_rate_1`, `disposal_rate_2` for all-cases, plus `_civil` / `_criminal` variants)
