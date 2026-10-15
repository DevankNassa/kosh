# Kosh — Product Specification (MVP)

| | |
|---|---|
| **Status** | Draft v0.2 — updated for the consultant's MFD registration |
| **Last updated** | 2026-10-15 |
| **Scope** | MVP only. Later phases are listed but not specified. |

> **Tax disclaimer:** the tax rules in this document are a working model for
> building the product. They are not tax advice. A Chartered Accountant must
> verify them before launch. Check them against the current Finance Act and
> the Income-tax Act, 2025 (in force from 1 April 2026; it renumbers the
> sections of the 1961 Act cited below).

---

## 1. Overview

### 1.1 Problem

An independent financial consultant manages investments for many individual
clients, mostly in Indian markets. Each client holds a mix of equities,
mutual funds, government and corporate bonds, and other instruments, spread
across several depositories and registrars. Today the consultant:

- puts together each client's holdings by hand from consolidated account
  statements (CAS PDFs) and spreadsheets;
- has no quick way to answer "which of my clients are affected by this rate
  change, rating downgrade or company news, and by how much?";
- works out the tax impact of rebalancing or selling by hand, lot by lot,
  for each client.

### 1.2 Product vision

**Kosh** is a back-office tool for the advisor. It brings every client's
portfolio into one view, explains how market moves and news events affect
each client, and shows the tax result of a portfolio change before the
change is made.

### 1.3 MVP goals

1. Import a client's holdings and transaction history from CAS PDFs in under
   a minute per statement, with no retyping.
2. Show each client's portfolio, valued at the latest end-of-day prices, with
   allocation broken down by asset class, sector, issuer, rating and maturity.
3. Every trading day, explain what moved each client's portfolio and flag
   clients exposed to relevant news (rate moves, rating actions, company
   announcements).
4. For any proposed sale or rebalance, show the realised gains, the tax due
   and the post-tax proceeds lot by lot, before the advisor acts.

### 1.4 Non-goals (MVP)

- Placing trades or connecting to brokers to execute orders.
- A client-facing app or login.
- Live (tick-by-tick) prices. End-of-day data is enough for an advisory workflow.
- Investment recommendations of any kind, automated or otherwise. The
  consultant is a Mutual Fund Distributor, not a SEBI-registered Investment
  Adviser, so Kosh is an **information, reporting and what-if tool**. It
  shows facts, exposures and tax consequences; it never tells anyone what
  to buy or sell (see §9).
- Full ITR filing or tax-return preparation.

---

## 2. Users

| User | Description | MVP? |
|---|---|---|
| **Advisor** (primary) | The consultant, an AMFI-registered Mutual Fund Distributor (ARN holder). Manages all clients, imports data, reviews impact, models changes. "Advisor" is used in this document as a role name only; the product UI must not describe him as an adviser (see §9.1). | ✅ |
| **Advisor staff** | Back-office assistant who imports statements and checks data. | Later (needs roles) |
| **Client** | End investor who views their own portfolio and reports. | Later |

The MVP is **single-tenant and single-user**: one advisor, one deployment,
with access to all client data.

---

## 3. Core workflows

These are the five workflows the MVP has to support from start to finish.

**W1. Onboard a client**
Create a client (name, PAN, tax residency, tax regime, slab, family group).
Upload their CAS PDF(s) with the PDF password. Review the parsed holdings and
fix any warnings. Confirm. The portfolio appears.

**W2. Monthly refresh**
Upload the new monthly CAS for one or more clients. Kosh matches it against
existing data. New transactions are added, holdings are reconciled, and
differences are flagged.

**W3. Morning review**
Open the dashboard and see:
- yesterday's book-wide change and each client's change, split into the
  instruments that caused it;
- news and events since the last session (RBI policy, rating actions,
  company announcements), each with the list of clients exposed and the size
  of their exposure.

**W4. "Who is affected by X?"**
Start from an event or instrument (e.g. "ABC Ltd downgraded to A-",
"10Y G-sec yield +25 bps", "Sector: PSU banks") and get every exposed client
with a rupee estimate of the impact.

**W5. Model a portfolio change and its tax cost**
For a client, enter the sells and buys being considered (or a target
allocation the client has chosen). Kosh works out the lots sold, shows STCG/LTCG for each lot, the use of the yearly
LTCG exemption, losses available to set off, the estimated tax, exit loads
and post-tax proceeds, and the new allocation. Export the plan as a PDF or
Excel file for the client conversation.

---

## 4. Functional requirements

Priority: **P0** = MVP must-have, **P1** = MVP if time allows, **P2** = later.

### F1. Client management (P0)

- F1.1 Create, edit and archive clients. Fields: name, PAN, DOB, residential
  status (Resident / NRI), tax regime (old/new), expected marginal slab,
  surcharge band, family group, notes.
- F1.2 Group clients into **families/households** (P1). Most advisors
  manage family portfolios together.
- F1.3 Record the client's **risk profile** (as stated by the client or
  from the distributor's own risk-profiling questionnaire) and the
  client's chosen **target allocation** (by
  asset class, and optionally by sub-class such as "Debt: G-sec / Corporate
  AAA / Corporate below AAA").
- F1.4 Record carried-forward capital losses from previous years, entered
  manually from the client's ITR (P0; the tax engine needs it).

### F2. Statement import (P0)

Supported sources in the MVP:

| Statement | Issuer | What it contains | Gaps |
|---|---|---|---|
| **MF CAS (detailed)** | CAMS / KFintech | All MF folios across AMCs, with **full transaction history** (purchases, redemptions, switches, SIPs, dividends, stamp duty, STT) | Mutual funds only |
| **Depository CAS** | NSDL / CDSL | Demat holdings (equity, ETFs, bonds, SGBs, demat MF units) with month-end values, plus that month's transactions | **No purchase cost or history before the statement period** |
| **Distributor feeds** (P1) | CAMS / KFintech distributor services | Transactions and holdings of clients mapped to the consultant's ARN, delivered as regular reports or files | Only covers folios under his ARN; formats and access to be confirmed with the RTAs |

Because the consultant is an MFD, the registrars already send him data on
the folios he distributes. Using these distributor feeds (P1) would keep MF
data current without asking clients for a new CAS every month. The client's
CAS stays the source of truth, because it also covers holdings bought
directly or through other distributors.

Requirements:
- F2.1 Upload password-protected PDFs (the password is normally PAN-based).
  Passwords are used in memory only and never stored.
- F2.2 Parse into structured holdings and transactions, keyed by **ISIN**.
- F2.3 Show an **import preview** before saving: holdings, transactions,
  totals checked against the statement's own totals, and warnings for
  unknown ISINs, a mismatched PAN, duplicates or parse failures.
- F2.4 **Idempotent re-import.** Importing the same statement twice must not
  duplicate data. Overlapping statements are deduplicated by transaction
  (folio/demat account, date, type, units, amount).
- F2.5 **Reconciliation.** After import, units derived from transactions
  must equal the units in the statement for every holding. Any mismatch is
  flagged for review.
- F2.6 **Cost basis for demat holdings.** The depository CAS does not carry
  acquisition cost, so the MVP must offer:
  - (P0) manual entry or bulk Excel/CSV upload of purchase lots
    (date, units, price) for each holding;
  - (P0) a **generic tradebook CSV template** that any broker's export can
    be pasted into, since we don't yet know which brokers clients use;
  - (P1) broker-specific **tradebook / tax P&L** parsers (Zerodha, Groww,
    ICICI Direct, etc.), built in the order shown by the broker report
    below;
  - (P0) a **"Depository participants in use" report**. The depository CAS
    names the depository participant (usually the client's broker) for each
    demat account, so after the first batch of imports Kosh can show which
    brokers clients actually use, and how much value sits with each. This
    answers Q3 from real data;
  - holdings without a cost basis are marked **"Cost unknown"**. They are
    valued normally but left out of tax calculations, with a visible warning.
- F2.7 Keep the original PDF (encrypted at rest) linked to the import record
  for audit purposes.

*Implementation note:* evaluate the open-source
[`casparser`](https://github.com/codereverser/casparser) library (Python)
for CAMS/KFintech and NSDL/CDSL parsing before writing a parser from
scratch. Keep a set of anonymised sample statements as regression fixtures.

### F3. Instrument master and pricing (P0)

- F3.1 A single **instrument master** keyed by ISIN, holding: name, type
  (equity, equity MF, debt MF, hybrid MF, ETF, G-sec, SDL, T-bill, corporate
  bond, SGB, other), issuer, sector/industry, listing status, and for MFs
  the AMFI scheme code, category and equity/debt classification for tax.
- F3.2 Bond attributes: face value, coupon, coupon frequency, issue date,
  maturity, call/put dates, credit rating and agency, secured/unsecured,
  listed/unlisted, and whether interest is tax-free.
- F3.3 Daily end-of-day price for every held instrument, with **price source
  and as-of date stored with each price**. Stale prices are flagged.
- F3.4 For bonds: yield to maturity, modified duration and convexity,
  calculated from price and cash flows.
- F3.5 Corporate actions (splits, bonuses, mergers, demergers, rights) adjust
  units and cost basis. In the MVP these are applied semi-manually: the
  advisor confirms each detected action (P1 to automate).

See **§5 Market data strategy** for sources.

### F4. Portfolio views (P0)

- F4.1 **Book overview:** total value tracked (and value under his ARN, P1), number of clients,
  day / month-to-date / year-to-date change, and the top movers among
  clients and instruments.
- F4.2 **Client portfolio:**
  - holdings table (instrument, units, average cost, current value,
    unrealised gain, holding period, tax status ST/LT);
  - allocation by asset class, sub-class, sector, issuer, credit rating,
    maturity bucket and AMC; current vs. target, with drift highlighted;
  - **look-through for mutual funds** (P1): break an MF holding down into
    its underlying stocks and sectors using the monthly portfolio
    disclosures AMCs publish, so the issuer and sector exposure is real;
  - returns: XIRR overall and per holding, and absolute returns;
  - debt summary: weighted average YTM, modified duration, and the
    maturity and coupon calendar.
- F4.3 **Daily change attribution:** each client's value change since the
  last close, split by instrument. This is the factual basis for "what
  happened to my portfolio".

### F5. Market and news impact (P0 core, P1 enhancements)

Kosh does not try to predict prices from news. It does two concrete things:

**(a) Exposure mapping (P0).** Every event is tagged to one or more
*exposure keys*, and Kosh lists every client holding those keys:

| Event type | Example | Exposure key | Impact estimate |
|---|---|---|---|
| Interest-rate / yield move | RBI repo cut; 10Y G-sec −15 bps | Debt holdings by duration bucket | ΔP ≈ −D<sub>mod</sub>·Δy·P + ½·C·Δy²·P per bond; debt MFs use their reported modified duration |
| Credit rating action | ABC Ltd AA → A+ (negative watch) | Issuer (direct bonds + MF look-through) | Exposure amount; optional spread-widening scenario |
| Company announcement | Results, M&A, default, fraud, block deal | Issuer / ISIN | Exposure amount + actual price move once available |
| Sector / policy news | New PLI scheme, regulatory change for NBFCs | Sector / industry | Exposure amount by client |
| Market-wide move | Nifty −3% | Equity beta (later) | Actual EOD attribution (F4.3) |

**(b) Scenarios (P0).** The advisor can apply a shock and see the
estimated impact on every client and on the whole book:
- parallel yield-curve shift (±bps);
- credit-spread widening for each rating bucket;
- equity index shock (±%), applied at portfolio level in the MVP;
- issuer default (write a named issuer down to X%).

**News ingestion:**
- F5.1 (P0) Pull structured event feeds on a schedule: exchange corporate
  announcements, RBI press releases and policy announcements, SEBI
  circulars, and rating-agency rating actions (see §5.4).
- F5.2 (P0) Match each event to instruments by ISIN or issuer name, using
  a hand-maintained alias table (e.g. "SBI" → State Bank of India).
- F5.3 (P1) LLM-assisted tagging: classify free-text news (event type,
  issuers, sectors, sentiment) and write a two-line summary. The output is
  shown as a *suggestion* with its source link, never as fact.
- F5.4 (P0) **Event inbox:** a list of new events, each showing the
  number of exposed clients and the total exposure. Clicking an event opens
  the W4 view.

### F6. Tax engine and rebalance planner (P0)

- F6.1 **Lot-level tracking** of every holding: acquisition date, units,
  cost, and the grandfathered fair market value on 31 Jan 2018 where it
  applies.
- F6.2 **Sale lot selection.** FIFO is mandatory for MF units and demat
  securities in India. The engine must use FIFO for each folio or demat
  account, and must not let the advisor pick lots.
  *(Tax-saving choices are made by choosing which holding, folio or account
  to sell, not which lot.)*
- F6.3 **Tax classification** of each lot on a given sale date, based on
  the rules table in §7, versioned by date.
- F6.4 **Realised gains to date** for the current financial year, split into
  STCG/LTCG and by tax rate category, including the LTCG exemption used
  so far and set-off of losses (current year and carried forward).
- F6.5 **What-if planner** (named so in the UI; not "recommendations"):
  - input: either a list of transactions being considered, or a target
    allocation the client has chosen, from which Kosh computes the trades
    needed to reach it (shown as a calculation, not advice);
  - output: units sold per lot, gains by category, estimated tax
    (including surcharge and cess), exit loads, STT and stamp duty, post-tax
    proceeds and the allocation after the change;
  - **side-by-side comparison** of 2–3 alternatives (e.g. "sell fund A"
    vs. "sell fund B" vs. "wait 23 days until lots become long-term");
  - **long-term soon flag:** lots that become long-term within N days
    (default 60), with the tax saved by waiting;
  - **LTCG exemption harvesting:** how much LTCG can be realised this
    financial year tax-free under the ₹1.25 lakh exemption;
  - **unrealised losses available:** unrealised losses that could offset
    gains already realised, shown as facts, not suggestions.
- F6.6 **Export** the plan as PDF and Excel (P0) for the client meeting.
  Every export carries a standard disclaimer (§9.1), the consultant's ARN,
  and the assumptions used.
- F6.7 **Assumptions panel:** every tax estimate shows the slab, regime
  and surcharge assumptions it used, and those can be overridden per plan.
- F6.8 (P2) ESOP/RSU module: see §7.4. In the MVP, ESOP/RSU shares that
  appear in the demat CAS are tracked like other equity, with the cost
  basis entered manually as the FMV at vest/exercise.

### F7. Alerts (P1)

Bond maturities, call/put dates and coupon payments in the next 30 days;
lots becoming long-term; allocation drift beyond a threshold; stale prices;
clients with no statement imported for more than 45 days.

### F8. Audit and records (P0)

- F8.1 Append-only audit log of imports, edits, overrides and generated
  plans (who, what, when, before/after).
- F8.2 Every exported plan is stored with the inputs, the prices and the
  rule version used to produce it, so it can be reproduced later.

---

## 5. Market data strategy

**Recommendation:** for the MVP, use **end-of-day (EOD) data from official,
free or low-cost sources**, accessed through a **provider abstraction
layer** so any source can be swapped for a paid vendor later without
changing the rest of the system. Do not buy a live feed for the MVP.
Advisory decisions are made on a daily cycle, and live data adds cost,
licensing obligations and complexity.

### 5.1 Principles

1. **ISIN is the universal key.** CAS statements, exchange price files and
   AMFI NAV files all carry ISINs, so they can be joined without fuzzy
   matching.
2. **Store provenance.** Every price, rating and yield carries its source,
   as-of timestamp and retrieval time.
3. **Prefer official files to scraping.** Use published data files and
   documented APIs. Exchange websites restrict automated scraping, so check
   each source's terms of use before using it in production.
4. **Separate "observed" from "model" prices.** Many Indian bonds rarely
   trade, so a model price must be labelled as indicative.

### 5.2 Sources by asset class

| Data | MVP source | Cost | Notes / later upgrade |
|---|---|---|---|
| **Mutual fund NAVs** | AMFI daily NAV file (all schemes, with ISINs and scheme codes) | Free | Reliable; the obvious choice. |
| **MF portfolio disclosures** (for look-through) | AMC monthly portfolio files / AMFI | Free | Formats vary by AMC; parsing effort is P1. Vendor: Value Research / Morningstar data feeds. |
| **Equity & ETF EOD prices** | NSE and BSE daily **bhavcopy** (end-of-day price files, with ISINs) | Free | Upgrade: authorised data vendor (e.g. TrueData, Global Datafeeds) or a broker data API if intraday is ever needed. |
| **Corporate actions** | NSE/BSE corporate action and announcement data | Free | Vendor feed later for reliability. |
| **G-secs, SDLs, T-bills** | **FBIL** daily valuation prices and yield curves; RBI / CCIL published data | Free | FBIL is the official benchmark administrator for G-sec valuation. |
| **Listed corporate bonds** | Exchange debt-segment trade reports (NSE/BSE) for traded prices, otherwise a **model price**: FBIL G-sec curve + credit spread for the rating and tenor bucket | Free (model) | Most corporate bonds trade thinly. Upgrade: **CRISIL or ICRA bond valuation** feeds (paid; industry standard used by MFs). |
| **SGBs** | Exchange bhavcopy (traded series); IBJA gold price for reference value | Free | — |
| **Credit ratings** | Rating-agency rating-action press releases (CRISIL, ICRA, CARE, India Ratings, Acuité, Brickwork) | Free | A licensed ratings feed later. |
| **Benchmarks / indices** | NSE index EOD data (Nifty 50, sectoral indices, debt indices) | Free (EOD) | Index licensing is needed if indices are redistributed to clients. |
| **Macro / policy** | RBI press releases, MPC statements, DBIE database | Free | — |

### 5.3 Pricing hierarchy for bonds

For each bond, on each day, use the first available of:
1. a traded price on the exchange that day (if volume is above a minimum);
2. a vendor valuation price (once a vendor is licensed);
3. a model price from the FBIL curve + rating/tenor spread matrix;
4. the last known price, marked **stale**.

The UI shows which level was used.

### 5.4 News and event sources (MVP)

| Feed | Gives | Matching |
|---|---|---|
| NSE/BSE corporate announcements | Results, board meetings, M&A, defaults, credit-related disclosures | By company → ISIN (exact) |
| Rating-agency rating actions | Upgrades, downgrades, watches, defaults | By issuer name → issuer ID via alias table |
| RBI press releases / MPC decisions | Policy rate decisions, regulatory actions | Macro: all debt holdings by duration |
| SEBI circulars / orders | Regulatory changes, enforcement orders | By entity or sector |
| General business news (P1) | Media coverage | LLM tagging (F5.3) via a licensed news API or RSS feeds that permit this use |

### 5.5 Budget guidance

- **MVP: about ₹0 per month in data costs.** Everything in the MVP column is
  public, plus hosting and an LLM API for tagging (P1).
- **First paid upgrade, when the advisor needs it:** a bond valuation feed
  (CRISIL/ICRA) for accurate corporate bond prices. This is the biggest
  quality gap in the free setup.
- **Decision rule for the bond feed.** We don't yet know how much of the
  book is in corporate bonds (Q4). At M2, Kosh produces a **bond exposure
  report**: value held directly in corporate bonds, split by listed/unlisted,
  rating and issuer type, and how much of it is priced by model rather than
  by trades. Buy a valuation feed if model-priced corporate bonds exceed
  roughly 10% of the book's value, or if the consultant finds the model
  prices unreliable in review. Corporate bonds held *inside debt mutual
  funds* don't need the feed: their value comes from the fund's daily NAV.
- **Second:** an authorised market data vendor, if intraday prices or
  guaranteed data quality are needed.

Get exact prices from vendors during the technical spec phase.

---

## 6. Conceptual data model

```
Client ──< Account (demat BO ID / MF folio) ──< Transaction
   │                                    └──< Lot (derived, FIFO)
   ├── TaxProfile (regime, slab, residency, carried-forward losses by FY)
   ├── TargetAllocation
   └── FamilyGroup (P1)

Instrument (ISIN) ── Issuer ──< IssuerAlias
   ├── BondTerms / MFScheme / EquityInfo
   ├──< Price (date, value, source, level)
   ├──< Rating (agency, rating, outlook, date)
   └──< CorporateAction

Event (type, source, timestamp, text, link)
   └──< EventTag (issuer | ISIN | sector | macro factor)

Import (file, source type, statement period, status, warnings)
Plan (client, inputs, rule version, price snapshot, outputs)
TaxRuleSet (effective_from, effective_to, rules…)
AuditLog
```

Key decisions:
- **Transactions are the source of truth.** Lots and holdings are derived
  from them and checked against statement balances.
- **Tax rules are data, not code.** Rules are stored as versioned rule sets
  with effective dates, so a sale is always evaluated under the rules in
  force on its transfer date, and next year's Budget changes mean adding a
  rule set, not rewriting the engine.

---

## 7. Tax rules model (residents, individuals)

These are the rules for transfers **on or after 23 July 2024**, as
understood at the time of writing. Earlier dates need the earlier rule set
(the engine must support at least FY 2023-24 onwards, for realised-gains
history).

### 7.1 Capital gains by instrument

| Instrument | Long-term if held > | STCG rate | LTCG rate | Notes |
|---|---|---|---|---|
| Listed equity shares (STT paid) | 12 months | 20% | 12.5% above ₹1.25 lakh/yr exemption | Grandfathering: cost = higher of actual cost and FMV on 31-Jan-2018 (capped at sale price) for shares bought before 1-Feb-2018 |
| Equity-oriented MFs (≥65% equity) | 12 months | 20% | 12.5% above ₹1.25 lakh | Exemption is shared with listed equity |
| "Specified" debt MFs, bought on/after 1-Apr-2023 | — | Slab | Slab | Always treated as short-term, whatever the holding period |
| Debt MFs bought before 1-Apr-2023 | 24 months | Slab | 12.5%, no indexation | |
| Other MFs (hybrid <65% equity, FoFs, gold/intl funds) | 24 months | Slab | 12.5% | Classification depends on scheme mandate and purchase date; keep it **per scheme** in the instrument master |
| Listed bonds / debentures | 12 months | Slab | 12.5%, no indexation | |
| Unlisted bonds / debentures | — | Slab | Slab | Always short-term |
| G-secs / SDLs (listed) | 12 months | Slab | 12.5% | |
| SGBs | 12 months (secondary sale) | Slab | 12.5% | **Exempt** when an individual holds to maturity/redemption with RBI |
| ETFs (equity) | 12 months | 20% | 12.5% above ₹1.25 lakh | Gold/debt ETFs follow their underlying classification |
| Unlisted / foreign shares (incl. foreign RSUs) | 24 months | Slab | 12.5% | |

### 7.2 Income (not capital gains)

- Bond/debenture interest, G-sec interest, FD interest, SGB interest
  (2.5%/yr): taxed at slab. TDS applies to listed debenture interest.
- Dividends (equity and MF IDCW): taxed at slab.
- Tax-free bonds: interest exempt; capital gains still taxable.

### 7.3 Computation rules

- Add surcharge (by income band; capped at 15% on STCG/LTCG under ss.
  111A/112A and on dividends) and 4% health & education cess.
- **Loss set-off:** short-term capital loss can be set off against STCG or
  LTCG; long-term capital loss only against LTCG. Unabsorbed losses carry
  forward for 8 years (only if the return was filed on time).
- Order of set-off should **minimise tax** (e.g. use losses against gains
  taxed at the highest rate before using up the ₹1.25 lakh exemption).
- Rebate u/s 87A does not apply to special-rate capital gains. Show a note
  rather than modelling edge cases.
- Exit loads reduce sale proceeds; STT is not deductible; stamp duty and
  brokerage are part of cost or deducted as transfer expenses as applicable.
- **NRI clients:** TDS at source on redemptions and different treaty
  treatment. The MVP *flags* NRI clients and shows gross estimates only (P2
  for full support).

### 7.4 ESOP / RSU (P2 module, specified here for completeness)

- **At vest/exercise:** perquisite = FMV on the exercise/allotment date −
  amount paid; taxed as salary at slab (the employer withholds TDS).
  Eligible startup employees can defer this tax.
- **At sale:** capital gain = sale price − FMV on the exercise date. Holding
  period starts on the exercise/allotment date. Listed Indian shares follow
  §7.1 listed equity; foreign shares follow the unlisted/foreign row.
- **Foreign holdings:** reporting in Schedule FA of the ITR (calendar-year
  basis) and foreign tax credit (Form 67). The module should produce the
  data for these.
- **Planner features:** vesting schedule import, projected perquisite tax
  per vest, and "sell-to-cover" vs. "hold" comparison.

---

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| **Security** | TLS everywhere; encryption at rest for the database and stored PDFs; PAN and other identifiers encrypted at field level; MFA for the advisor login; CAS passwords never stored. |
| **Privacy (DPDP Act, 2023)** | Get and record client consent for processing; collect only the data needed; deletion on request; breach notification process; data stored in India. |
| **Availability** | Daily batch (prices, events) completes by 8:00 IST. The app works with yesterday's data if a batch fails, with a visible banner. |
| **Accuracy** | Imported holdings reconcile to statement totals to the paisa/unit; the tax engine is covered by a CA-reviewed test suite of worked examples. |
| **Performance** | Portfolio pages load in < 2 s for a client with 500 lots; whole-book scenario runs in < 10 s for 500 clients. |
| **Backups** | Daily encrypted backups, 30-day retention, restores tested quarterly. |
| **Auditability** | See F8. |

---

## 9. Compliance considerations

### 9.1 The consultant is a Mutual Fund Distributor (decided)

The consultant is an **AMFI-registered Mutual Fund Distributor (MFD)**, not
a SEBI-registered Investment Adviser (RIA). Under SEBI's Investment Adviser
Regulations and the AMFI code of conduct, an MFD earns commission from fund
houses, may give only advice that is *incidental* to the products they
distribute, may not charge clients a fee for advice, and may not call
themselves an "adviser" or "wealth adviser". This shapes the product:

| Area | What Kosh does |
|---|---|
| **Positioning** | Kosh is a portfolio information, reporting and what-if tool for the distributor. No screen, export or LLM output recommends buying or selling anything. |
| **Wording** | UI and exports use "portfolio review", "what-if", "scenario", "impact"; never "advice", "recommendation" or "adviser". Exports show the consultant as "AMFI-registered Mutual Fund Distributor, ARN-XXXX". |
| **What-if planner** | Only models changes the consultant or client enters, or a target allocation the client has chosen. Kosh never generates a list of what to sell. |
| **Disclaimer** | Every export and client-facing view carries a standard disclaimer (wording to be reviewed by a compliance professional): not investment advice; mutual fund investments are subject to market risks; tax estimates are indicative and should be confirmed with a tax professional. |
| **Non-MF products** | Distributing bonds or stocks needs separate arrangements (e.g. being an Authorised Person of a stock broker, or partnering with a SEBI-registered online bond platform). Kosh *tracks and reports* these holdings either way; it does not imply he advises on them. See Q10. |
| **Fee model** | Kosh has no billing or advisory-fee features. |
| **Records** | The audit log (F8) records every what-if and export, which helps show that the consultant provided information rather than paid advice. |

**If the consultant later registers as an RIA**, the same design extends to
advice: add advice records, suitability assessments, and fee billing. The
data model does not need to change.

### 9.2 Human in the loop

Kosh shows exposures, impacts and tax consequences; people decide. Any
LLM-generated text is labelled as such, links to its sources, and is
checked against the wording rules in §9.1.

---

## 10. Proposed architecture (to be confirmed in the technical spec)

- **Backend:** Python (FastAPI). Python has the strongest ecosystem for PDF
  parsing (`casparser`, `pdfplumber`), data processing (`pandas`) and
  fixed-income maths.
- **Database:** PostgreSQL.
- **Jobs:** a scheduled worker for daily data loads (prices, events,
  ratings) and impact calculations.
- **Frontend:** React (Next.js) web app, used on desktop; responsive enough
  for a tablet in client meetings.
- **Market data:** provider interfaces (`PriceProvider`, `EventProvider`,
  `RatingProvider`, `CurveProvider`) with one adapter per source.
- **LLM (P1):** Claude API for news tagging and summaries, behind an
  interface; prompts and outputs are logged.
- **Hosting:** a cloud region in India (e.g. Mumbai), for data-residency
  reasons.

---

## 11. Milestones

| # | Milestone | Contents | Exit criterion |
|---|---|---|---|
| M0 | Foundations | Repo, CI, data model, auth, instrument master seed | Advisor can log in; ISIN master loaded |
| M1 | Import | F1, F2 (MF CAS + depository CAS + manual cost lots) | 10 real (anonymised) client statements import and reconcile |
| M2 | Valuation | F3, F4 with daily EOD jobs (AMFI, bhavcopy, FBIL, model bond pricing); bond exposure report (§5.5) | All holdings valued daily; attribution matches statement values within tolerance; bond feed decision made |
| M3 | Tax | F6 engine + planner + exports, CA-reviewed test cases | CA signs off on 30+ worked examples |
| M4 | Impact | F5 event feeds, exposure mapping, scenarios, event inbox | Advisor uses the morning review (W3) for 2 weeks |
| M5 | Pilot | Fixes, F7 alerts (P1), hardening, backups | Advisor runs their whole book on Kosh |

---

## 12. Open questions

| # | Question | Owner | Impact |
|---|---|---|---|
| ~~Q1~~ | ~~Is the consultant an RIA, an MFD, or both?~~ **Answered: MFD.** See §9.1. | — | — |
| Q2 | How many clients, and roughly how many holdings per client? | Consultant | Performance targets, pricing |
| Q3 | Which brokers do clients use? **Unknown; Kosh will measure it** from the first CAS imports (F2.6 depository participant report). | Kosh data, M1 | Order of broker-specific parsers |
| Q4 | How much of the book is in corporate bonds, and of what type (PSU, NBFC, perpetual, unlisted)? **Unknown; Kosh will measure it** with the bond exposure report at M2. | Kosh data, M2 | Whether to buy a paid bond valuation feed (decision rule in §5.5) |
| Q5 | Holdings outside CAS: FDs, PPF, NPS, PMS, AIFs, insurance, real estate. Are they needed in the MVP (manual entry)? | Consultant | Scope of F1/F4 |
| Q6 | Any NRI clients? How many? | Consultant | Tax engine scope |
| Q7 | Will the advisor's staff use Kosh? | Consultant | Roles and permissions |
| Q8 | Which reports does he share with clients today, and in what format? | Consultant | F6.6 export design |
| Q9 | Hosting and budget constraints | Product owner | Architecture, vendor choices |
| Q10 | How does the consultant arrange bond and stock investments for clients (Authorised Person of a broker, online bond platform partner, or clients invest on their own)? | Consultant | Positioning of non-MF holdings in exports; possible platform data imports |
| Q11 | Does he want commission/trail tracking by ARN (which AUM is under his ARN vs. bought direct or via others)? | Consultant | Possible P1 feature using distributor feeds |

---

## 13. Glossary

- **CAS:** Consolidated Account Statement. MF CAS comes from CAMS/KFintech
  (the registrars); depository CAS comes from NSDL/CDSL.
- **ISIN:** International Securities Identification Number; the universal
  identifier for a security.
- **Bhavcopy:** an exchange's daily end-of-day price file.
- **FBIL:** Financial Benchmarks India Ltd; publishes official G-sec
  valuations and benchmark curves.
- **AMFI:** Association of Mutual Funds in India; publishes daily NAVs.
- **STCG / LTCG:** short-term / long-term capital gains.
- **Modified duration:** the approximate % change in a bond's price for a
  1% change in yield.
- **XIRR:** annualised return that accounts for the timing of cash flows.
- **RIA / MFD:** SEBI Registered Investment Adviser / Mutual Fund Distributor.
- **ARN:** AMFI Registration Number, the identifier of a registered MFD.
- **RTA:** Registrar and Transfer Agent (CAMS, KFintech), which keeps
  mutual fund investor records.
- **DPDP Act:** Digital Personal Data Protection Act, 2023.
