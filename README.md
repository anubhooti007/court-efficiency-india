# Annual Survey of Industries (ASI) — Dataset Guide

> Documentation for India's **Annual Survey of Industries (ASI)** microdata, published by the
> **National Statistical Office (NSO) / Industrial Statistics (IS) Wing, Ministry of Statistics &
> Programme Implementation (MoSPI)** on the NADA microdata portal.
>
> Source catalog: <https://microdata.gov.in/NADA/index.php/catalog/ASI>

---

## 0. Read this first — status of this repository

**This folder currently contains documentation only. It does NOT contain the ASI data files.**

- The ASI microdata is hosted on the MoSPI NADA portal, and the actual unit-level data files
  (`.csv` / `.dta` / `.txt`) are **behind a free login/registration**. The "Get Microdata" page for
  every round returns *"Login to access data … register for a free account."*
- What **is** public without login: the **catalog listing**, **study descriptions**, and the
  **data dictionaries** (file lists, row/column counts, variable names, types, and value
  frequencies). This README is built from that public metadata layer.
- To populate this folder with real data, see **Section 9 — How to obtain the data**.

Everything below (schemas, keys, row counts, category codes) was verified against the live NADA
data-dictionary pages for **ASI 2018-19** (`catalog id 150`, `DDI-IND-NSO-ASI-2018-19`), which is the
representative modern round. Other rounds share the same block structure with minor year-to-year
variable changes.

---

## 1. What ASI is

The **Annual Survey of Industries** is the principal source of industrial statistics for India's
**registered (formal) manufacturing sector**. It covers factories registered under Sections
2(m)(i) and 2(m)(ii) of the **Factories Act, 1948** (plus bidi/cigar establishments, electricity,
gas & water undertakings, cold storage, and repair services).

- **Primary unit of enumeration:** a **factory** (or workshop / undertaking / establishment).
- **Legal basis:** Collection of Statistics Act (1953, later 2008).
- **Geographic coverage:** entire country, down to **state** (and district code) level.
- **Frequency:** annual; each fiscal year (April→March) is published as a **separate study**.
- **Sampling design:** part **census** (large factories, and "census scheme" states) + part
  **sample** (smaller factories). Every record carries a **multiplier / weight** so the sample can
  be grossed up to population totals.

> **This is a repeated cross-section, not a firm-level panel.** The public files are not designed to
> track the same factory across years (see Section 6, "Limitations").

---

## 2. The collection: 52 rounds, 1974-75 → 2023-24

The ASI collection on NADA contains **52 studies**. Each is one fiscal year. Naming conventions:

| Era | Reference ID pattern | Example |
|---|---|---|
| Recent (NSO) | `DDI-IND-NSO-ASI-YYYY-YY` | `DDI-IND-NSO-ASI-2023-24` |
| Older (CSO) | `IND-CSO-ASI-YYYY-YY[-v1]` | `IND-CSO-ASI-2012-13`, `IND-CSO-ASI-2010-11-v1` |
| Summary-only | `IND-CSO-ASI-SUMMARY-YY-YY` | `IND-CSO-ASI-SUMMARY-92-93` |

Notes:
- Rounds up to roughly **2014-15** carry a **`-v1` version suffix**; later rounds do not.
- Several early years exist **both** as a full unit-level study **and** a separate **"Summary"**
  study (e.g. 1993-94, 1984-85, 1994-95). The Summary studies are aggregated tables, not unit records.
- Time coverage of unit-level microdata is effectively **continuous from the mid-1990s onward**, with
  sparser/summary coverage for the 1970s–1980s.
- The **latest available round is 2023-24**; the newest with a fully verified block schema in this
  guide is **2018-19**.

Each round's landing page uses a numeric `catalog id` in the URL (e.g. `2018-19 → /catalog/150`).
The numeric id ≠ the year; resolve it from the collection listing.

---

## 3. Structure of a single round — 10 Block files (A–J)

A round is delivered as **10 flat files, one per survey "Block"**. The survey schedule's blocks map
1:1 to the data files. Verified counts for **ASI 2018-19**:

| File | Block | Contents | Rows (cases) | Cols | One row represents |
|---|---|---|---|---:|---|
| `blkA201819` | **A** | Identification + key aggregates + weight | **67,356** | 22 | **one factory** (master record) |
| `blkB201819` | **B** | Owner / organisation details | 67,356 | 12 | one factory |
| `blkC201819` | **C** | Fixed assets | 566,710 | 15 | one **asset-type line** per factory |
| `blkD201819` | **D** | Working capital & loans | 940,678 | 6 | one **line item** per factory |
| `blkE201819` | **E** | Employment & labour cost | 501,615 | 10 | one **worker-category line** per factory |
| `blkF201819` | **F** | Other expenses | 54,781 | 15 | one factory (subset) |
| `blkG201819` | **G** | Other output / receipts | 49,490 | 15 | one factory (subset) |
| `blkH201819` | **H** | Input items — indigenous (consumed) | 554,316 | 9 | one **input item** per factory |
| `blkI201819` | **I** | Input items — directly imported (consumed) | 30,859 | 9 | one **imported item** per factory |
| `blkJ201819` | **J** | Products & by-products (manufactured) | 133,299 | 15 | one **product line** per factory |

**Shape of the data:**
- **`blkA` and `blkB` are "wide"** — exactly **one row per factory** (both have 67,356 rows).
- **`blkC/D/E/H/I/J` are "long"/transactional** — many rows per factory, keyed by factory + a serial
  number. Approx lines per factory: C ≈ 8.4, D ≈ 14.0, E ≈ 7.4, H ≈ 8.2, J ≈ 2.0.
- **`blkF/G` and `blkI` are partial-coverage** — only factories that reported those items appear:
  F ≈ 81%, G ≈ 73%, **I (imports) ≈ 46%** of the 67,356 factories.

> Row counts differ every year with the sample size (e.g. ~67k factories in 2018-19). The **block
> structure and keys are stable** across modern rounds.

---

## 4. How the files join — keys

Every block shares three leading identifier columns:

| Column | Meaning | Notes |
|---|---|---|
| `YR` | Survey year | e.g. `1819` for 2018-19 |
| `BLK` | Block tag | identifies which block the row belongs to |
| **`DSL`** | **Dispatch Serial — the factory ID** | **the join key** |

`DSL` appears under a block-specific variable code but always means the same factory:

```
blkA.A1  (Dispatch Serial number)   ← master
blkB.AB01 = DSL
blkC.AC01 = DSL
blkD.AD01 = DSL
blkE.AE01 = DSL
blkF.AF01 = DSL
blkG.AG01 = DSL
blkH.AH01 = DSL
blkI.AI01 = DSL
blkJ.AJ01 = DSL
```

**Join model (within one year):**

```
blkA (1 row / factory)  ──DSL──┐
blkB (1 row / factory)  ──DSL──┤
blkC..blkJ (many rows / factory) ──DSL──┘   join on (YR, DSL)
```

- To build a **factory-level analysis table**: start from `blkA` (+ `blkB`), then **aggregate** each
  long block to the factory (sum values by `DSL`) before joining, or join and group.
- The **`(YR, DSL)`** pair is unique per factory **within a year only**. There is **no documented key
  that links the same factory across different years** in the public data.

---

## 5. Column reference (ASI 2018-19, verified)

Money values are in **Rupees (Rs.)**; quantities to 2 decimals. All fields are stored as plain
**Numeric** (Discrete or Continuous) — no currency symbols or units embedded in the values.

### Block A — `blkA201819` — Identification (the master, 22 vars)
One row per factory. Also carries a few pre-computed aggregates and the **weight**.

| Var | Label | Role |
|---|---|---|
| `YR` | Year | key |
| `BLK` | Block | key |
| `A1` | Dispatch Serial number | **factory ID (DSL)** |
| `A2` | PSL | frame serial |
| `A3` | **Scheme** | **1 = Census, 2 = Sample** (verified: 64.9% / 35.1%) |
| `A4` | Industry code as per **Frame** (NIC-2008, 4-digit class) | industry |
| `A5` | Industry code as per **Return** (NIC-2008, 5-digit sub-class) | industry |
| `A7` | **State code** | geography |
| `A8` | **District code** | geography |
| `A9` | **Sector (Rural / Urban)** | geography |
| `A10` | RO/SRO code | admin (regional office) |
| `A11` | No. of Units | consolidation count |
| `A12` | **Status of Unit** | 8 codes; **1 = open/operating (78.5%)**, 4 ≈ closed/non-response (10.6%), etc. Use to filter to live factories |
| `BONUS` | Bonus (Rs.) | labour cost |
| `PF` | Contribution to provident & other funds (Rs.) | labour cost |
| `WELFARE` | Workmen & staff welfare expenses (Rs.) | labour cost |
| `MWDAYS` | Working days — Manufacturing | activity |
| `NWDAYS` | Working days — Non-manufacturing | activity |
| `WDAYS` | Working days — Total | activity |
| `COSTOP` | Total cost of production | derived aggregate |
| `EXPSHARE` | Share (%) of products/by-products directly exported | export orientation |
| `MULT` | **Multiplier (weight), format 9999.99999999** | **sampling weight — required for all population estimates** |

### Block B — `blkB201819` — Owner / organisation (12 vars)
| Var | Label |
|---|---|
| `YR`,`BLK`,`AB01(DSL)` | keys |
| `B02` | Type of organisation |
| `B03` | Corporate Identification Number (CIN) |
| `B04` | ISO 14000-series certification? |
| `B05` | Year of initial production |
| `B06F` / `B06T` | Accounting year (from / to) |
| `B07` | Number of months of operation |
| `B08` | Share capital includes foreign entities? (1 Yes / 2 No) |
| `B09` | R&D unit in factory? (1 yes+DST/DBT, 2 yes+other, 3 no) |

### Block C — `blkC201819` — Fixed assets (15 vars, long by asset type)
| Var | Label |
|---|---|
| `YR`,`BLK`,`AC01(DSL)` | keys |
| `C_11` | S.No. (asset-type serial) |
| `C_13` | Gross value — opening |
| `C_14` | Gross value — addition due to revaluation |
| `C_15` | Gross value — **actual addition (investment)** |
| `C_16` | Gross value — deduction & adjustment |
| `C_17` | Gross value — closing |
| `C_18` | Depreciation up to year beginning |
| `C_19` | **Depreciation provided during the year** |
| `C_110` | Depreciation adjustment (sold/discarded) |
| `C_111` | Depreciation up to year end |
| `C_112` | Net value — opening |
| `C_113` | **Net value — closing (capital stock)** |

### Block D — `blkD201819` — Working capital & loans (6 vars, long)
| Var | Label |
|---|---|
| `YR`,`BLK`,`AD01(DSL)` | keys |
| `D11` | S.No. (line item) |
| `D13` | Opening (Rs.) |
| `D14` | Closing (Rs.) |

### Block E — `blkE201819` — Employment & labour cost (10 vars, long by worker category)
| Var | Label |
|---|---|
| `YR`,`BLK`,`AE01(DSL)` | keys |
| `E11` | S.No. (worker category: workers/employees/etc.) |
| `E13` | Man-days worked — Manufacturing |
| `E14` | Man-days worked — Non-manufacturing |
| `E15` | **Man-days worked — Total** |
| `E16` | **Average number of persons worked** |
| `E17` | No. of man-days paid for |
| `E18` | **Wages / salaries (Rs.)** |

### Block F — `blkF201819` — Other expenses (15 vars)
Keys + `F1` work done by others, `F2A/F2B` repair & maintenance, `F3` operating expenses,
`F4` raw material for own construction, `F5` insurance, `F6` rent of P&M, `F7` **R&D expenses**,
`F8` building rent, `F9` land rent/royalties, `F10` **interest paid**, `F11` purchase value of goods
sold as-is.

### Block G — `blkG201819` — Other output / receipts (15 vars)
Keys + `G1` manufacturing-services receipts, `G2` non-manufacturing services, `G3` **electricity sold**,
`G4` own construction, `G5` net balance of goods sold as-is, `G6` rent of P&M received, `G7` variation
in semi-finished stock, `G8` building rent received, `G9` land rent/royalties received,
`G10` **interest received**, `G11` sale value of goods sold as-is, `G12` other production subsidies.

### Block H — `blkH201819` — Indigenous inputs consumed (9 vars, long by item)
| Var | Label |
|---|---|
| `YR`,`BLK`,`AH01(DSL)` | keys |
| `H11` | S.No. |
| `H13` | **Item code (NPCMS commodity code)** |
| `H14` | Unit of quantity (code) |
| `H15` | Quantity consumed |
| `H16` | **Purchase value (Rs.)** |
| `H17` | Rate per unit (Rs.) |

### Block I — `blkI201819` — Imported inputs consumed (9 vars, long by item)
Same schema as H (`AI01, I11, I13 NPCMS, I14 unit, I15 qty, I16 value, I17 rate`) — but **only for
directly imported items**, so only ~46% of factories appear.

### Block J — `blkJ201819` — Products & by-products (15 vars, long by product)
| Var | Label |
|---|---|
| `YR`,`BLK`,`AJ01(DSL)` | keys |
| `J11` | S.No. |
| `J13` | **Item code (NPCMS)** |
| `J14` | Unit of quantity |
| `J15` | Quantity manufactured |
| `J16` | Quantity sold |
| `J17` | **Gross sale value (Rs.)** |
| `J18` | GST (Rs.) |
| `J19` | Excise / Sales Tax / VAT / other taxes (Rs.) |
| `J110` | Others (Rs.) |
| `J111` | Subsidy (Rs.) |
| `J112` | Per-unit net sale value (Rs.) |
| `J113` | **Ex-factory value of quantity manufactured (Rs.)** |

### Classification systems used
- **NIC-2008** — National Industrial Classification (`A4` 4-digit, `A5` 5-digit) → *what the factory
  produces / which industry it belongs to*.
- **NPCMS** — National Product Classification for Manufacturing Sector (`H13`, `I13`, `J13`) → *which
  commodity each input/output line is*.
- **Unit-of-quantity codes** (`H14`, `I14`, `J14`) → decode kg/tonne/number/litre/etc.
- **State/District codes** (`A7`, `A8`) → NSO state & district scheme.

> Category **value labels** (the text for each code) are largely blank in the online dictionary; the
> **code→label lookups live in the round's official documentation** ("Detailed description of items",
> "List of items with NPCMS/NIC codes"), downloadable from each study's **Downloads / Related
> materials** tab. Grab those alongside the data.

---

## 6. Data quality & limitations

- **Weights are mandatory.** Any population/aggregate estimate must use `MULT` (blkA). Census units
  have `MULT = 1`; sampled units > 1. Ignoring weights biases totals heavily toward large factories.
- **Repeated cross-section, not a panel.** `DSL` is unique **within a year**; the public files provide
  **no stable cross-year factory identifier**. Longitudinal firm-level tracking is not supported.
- **Status filtering.** `A12` (Status of Unit) includes closed / non-responding / deregistered units.
  Most analyses filter to **open/operating** units (code 1 ≈ 78.5% in 2018-19) — decide explicitly.
- **Partial-coverage blocks.** Blocks F, G, and especially **I (imports, ~46%)** do not cover all
  factories. A missing block row means "not reported," which is **not** the same as zero — handle
  the join with left-joins and treat absence deliberately.
- **Missing-value sentinels.** ASI files conventionally use blanks / `0` / negative sentinel codes
  (e.g. `-9`) for not-applicable or not-reported. Confirm per column against the round's codebook
  before treating values as numeric.
- **Classification revisions over time.** NIC and NPCMS code sets are revised between rounds (e.g.
  NIC-2004 vs NIC-2008). Naive year-over-year joins on raw codes will mismatch — use official
  concordances when building a time series.
- **Long-format traps.** blkC/D/E/H/I/J have multiple rows per factory. Joining blkA to a long block
  **without aggregating first fans out rows** and double-counts blkA aggregates. Aggregate long blocks
  to `DSL` before merging, or be careful with group-by.
- **Definitional consistency.** Some aggregates (e.g. `COSTOP`, working days) are pre-computed in
  blkA; verify they reconcile with the component blocks before mixing sources.
- **Access friction.** Data requires a free NADA login; there is no anonymous bulk API for the files.

---

## 7. What one row means (quick reference)

| File | One row = | Unique within a year by |
|---|---|---|
| blkA | a factory (master + weight) | `DSL` |
| blkB | a factory (owner info) | `DSL` |
| blkC | a fixed-asset category for a factory | `DSL + C_11` |
| blkD | a working-capital/loan line for a factory | `DSL + D11` |
| blkE | a worker category for a factory | `DSL + E11` |
| blkF | a factory's other-expense record | `DSL` |
| blkG | a factory's other-receipts record | `DSL` |
| blkH | an indigenous input item for a factory | `DSL + H11` |
| blkI | an imported input item for a factory | `DSL + I11` |
| blkJ | a product/by-product for a factory | `DSL + J11` |

---

## 8. Analyses, derived metrics & models you can build

Because ASI is **industrial/economic** microdata (not market/trading data), the high-value outputs are
productivity, cost-structure, and industrial-structure analyses. All should be **weighted by `MULT`**.

**Core derived metrics (factory level):**
- **Gross Value of Output (GVO)** = Σ blkJ `J17` (sale value) + blkG receipts + stock variation.
- **Total Input** = Σ blkH `H16` + Σ blkI `I16` (materials/fuels) + blkF operating expenses.
- **Gross Value Added (GVA)** = GVO − Total Input.
- **Net Value Added (NVA)** = GVA − depreciation (blkC `C_19`).
- **Employment** = blkE `E16` (avg persons worked); **Man-days** = `E15`.
- **Wage bill** = blkE `E18` (+ blkA `BONUS`,`PF`,`WELFARE`).
- **Capital stock** = blkC `C_113` (net closing value); **Investment** = blkC `C_15`.

**Ratios & indicators:**
- Labour productivity = NVA / persons (`E16`); NVA per man-day (`/E15`).
- Wage share = wage bill / NVA; average wage = `E18 / E16`.
- Capital intensity = capital stock / persons; capital productivity = NVA / capital.
- Profit proxy = NVA − wage bill − rent − interest (blkF `F10`, blkG `G10`).
- Import dependence = Σ blkI value / (Σ blkH + Σ blkI); export orientation = blkA `EXPSHARE`.
- Depreciation rate = `C_19 / C_112`.

**Structural / cross-sectional analyses:**
- **Industry** (NIC `A4/A5`): value added, employment, HHI concentration, wage differentials.
- **Geography** (state `A7`, district `A8`, sector `A9`): regional manufacturing maps, urban vs rural.
- **Organisation** (blkB `B02`): productivity by ownership type; foreign-capital (`B08`) and R&D
  (`B09`, blkF `F7`) effects.
- **Input–Output**: NPCMS-level product↔input matrices from blkH/I/J.
- **Formality & scale**: distribution of factory size, wage inequality across the size distribution.

**Time series (with care):**
- Stack multiple rounds to study trends in output, employment, wage share, capital deepening, and
  formal-sector growth from the 1990s to 2023-24 — after harmonising NIC/NPCMS codes and always
  applying weights. (Remember: aggregate trends only; **no firm-level panel**.)

**Modelling:**
- Production functions / **TFP** estimation (Cobb-Douglas / translog; Levinsohn-Petrin, Olley-Pakes).
- Returns-to-scale and markup estimation by industry.
- Determinants of productivity (R&D, imports, ownership, region) via weighted regressions.
- Predictive/classification models are secondary here — the dataset's strength is descriptive and
  causal industrial economics, not forecasting.

---

## 9. How to obtain the data

1. Create a **free account** at <https://microdata.gov.in/NADA/index.php/auth/register>.
2. Open the round you want, e.g. ASI 2018-19: <https://microdata.gov.in/NADA/index.php/catalog/150>.
3. Go to **Get Microdata** (login required) and download the block files (CSV/Stata/text).
4. Also download, from **Downloads / Related materials**, the round's **codebook / detailed item
   descriptions** and **NIC & NPCMS code lists** — you need these to decode categorical values and
   product/industry codes.
5. Suggested local layout to mirror this documentation:

```
ASI/
├── README.md                ← this file
├── raw/
│   └── 2018-19/
│       ├── blkA201819.csv
│       ├── blkB201819.csv
│       ├── … blkC … blkJ …
│       └── docs/            ← codebook, NIC/NPCMS lists, schedule
├── raw/2019-20/ …
└── work/                    ← cleaned/derived tables (weighted GVA, panels of aggregates, etc.)
```

Public metadata (no login) for automation:
- Study page: `…/catalog/{id}`
- Data dictionary (file list): `…/catalog/{id}/data-dictionary`
- Per-file variables: `…/catalog/{id}/data-dictionary/F{n}?file_name=…`
- Per-variable stats/categories: `…/catalog/{id}/variable/F{n}/V{m}?name=…`
- Machine-readable metadata: `…/metadata/export/{id}/ddi` (DDI/XML) and `…/metadata/export/{id}/json`

---

## 10. Recommended next steps

1. **Register and download one recent round** (e.g. 2018-19 or 2022-23) plus its codebook.
2. **Verify this schema against the actual files** (column order, sentinel/missing codes, value
   labels) — do not assume; confirm from the downloaded data + codebook.
3. Build a reusable **loader** that: reads all 10 blocks, aggregates long blocks to `DSL`, joins to
   blkA/blkB, and attaches `MULT`.
4. Produce a **weighted factory-level analysis table** with GVO/GVA/NVA, employment, wage bill, and
   capital — the foundation for everything else.
5. Add **NIC/NPCMS concordances** and stack multiple rounds for weighted time-series aggregates.
6. Only then layer on modelling (TFP/production functions) and cross-sectional studies.

---

## Appendix — provenance of this document

- Built from the **public NADA metadata** for the ASI collection and, in detail, from
  **ASI 2018-19** (`DDI-IND-NSO-ASI-2018-19`, catalog id 150).
- Verified live: collection listing (52 studies), the 10-file data dictionary with row/column counts,
  the full variable list for every block A–J, and sample variable-level statistics/category codes
  (`A3` Scheme, `A12` Status of Unit).
- **Not** verified from raw data (login-gated): exact byte-level column order, missing-value
  sentinels, and category label text — confirm these from the official codebook after download.
- Row counts, coverage percentages, and category shares quoted here are **specific to ASI 2018-19**
  and will differ in other rounds.
