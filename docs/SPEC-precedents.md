# Kosh — Feature spec: Past similar events ("Precedents")

| | |
|---|---|
| **Status** | Draft v0.1, for discussion with the consultant before any code |
| **Requested by** | The consultant (client), Oct 2026 |
| **Extends** | `SPEC.md` F5 (Market and news impact) |
| **Touches** | `impact/historical.py`, `models.py` (`Event`), Events and Scenarios pages |

---

## 1. What the client asked for

> Whenever a news event comes in, look into the past for similar news, list
> what happened to different families of stocks, and predict the probability
> of what will happen in the future.

That breaks into four questions, and each one needs a design decision:

1. **What triggers it?** A "news event coming in" (§3).
2. **What counts as "similar"?** How past events are found and matched (§4).
3. **What is a "family of stocks", and what "happened" to it?** The
   measurement (§5).
4. **What does "probability" mean here?** This one has a compliance problem,
   so it is covered first (§2).

---

## 2. The compliance constraint, and how we reframe "predict"

`SPEC.md` §9.1 and F5 say Kosh is an information tool for an AMFI-registered
MFD and that it "does not try to predict prices from news". A screen saying
"72% chance Nifty IT falls next week" reads as a forecast. Next to a client's
holdings it reads as a nudge to sell. An MFD shouldn't show that, and SEBI's
and AMFI's rules on performance projections apply.

**Proposed reframing: show history, not a forecast.** Kosh reports what
happened after past similar events, along with the normal rate for
comparison:

> After **9** past events like this, Nifty Oil & Gas was **lower 10 trading
> days later in 7 of 9** (median **−4.1%**, range −11.8% to +2.3%). In an
> ordinary 10-day period since 2020 it is lower **46%** of the time.

This answers the client's actual question ("how likely is a fall, going by
history?") without Kosh making a prediction. The number is a count of past
events, the sample size is always on screen, and the normal rate stops
"7 of 9" from looking more meaningful than it is.

Rules for the feature (they extend §9.1):

- Wording is about the past: "after past similar events", "was lower in
  X of N". Never "will", "expected to", "likely to", "forecast", "target",
  "buy", "sell", "exit", "switch".
- Every result shows **N** (how many past events) and the **normal rate**.
  If N < 5, no percentage is shown; the page just lists the events with
  "Too few past events to summarise".
- Fixed disclaimer: *"Past market behaviour after similar events. Not a
  forecast and not investment advice. Past performance may or may not be
  sustained in future."* (Wording to be checked by a compliance
  professional.)
- **Internal only in v1.** Results are not included in client exports
  until compliance has reviewed the wording (CLIENT_QUESTIONS.md P2).
- No statistical or ML forecasting model in v1. With 5 to 30 relevant
  events since 2020, a fitted model would overfit and look more precise
  than it is. Counts, medians and ranges are honest about how little data
  there is.

**This changes a decision already recorded in CLAUDE.md / SPEC F5, so the
consultant needs to agree to this framing before we build (CLIENT_QUESTIONS.md P1).**

---

## 3. Trigger: where "a news event" comes from

There is no automated news feed today. Events are entered by hand on the
Events page (`POST /api/events`), and the feeds in SPEC F5.1 haven't been
built. So:

- **v1:** the trigger is any `Event`, whether typed in or added later by a
  feed. When an event is created, or opened on the Events page, Kosh
  computes its precedents. Results are cached and recomputed when the
  event's tags change or new prices arrive.
- **Later:** when the F5.1 feeds (RBI, SEBI, exchange announcements,
  rating actions) exist, each event they create triggers the same thing.
  Precedents don't depend on the feeds and shouldn't wait for them.

For an event to be matched it needs a **type** from the event taxonomy in
§4.1. On the event form this is a required dropdown. Later it can be
suggested by the LLM tagging in F5.3, shown as a suggestion the consultant
confirms.

---

## 4. Finding similar past events

### 4.1 Option chosen: a curated library with a fixed taxonomy

Three options were considered:

| Option | How it matches | Verdict |
|---|---|---|
| **A. Taxonomy + tags** | Each event has a type (e.g. `rbi_rate_cut`) and tags (sector, direction, size, region). Similar means same type, then ranked by how many tags match. | **v1.** Easy to explain ("matched because: RBI repo cut, 25 bps"), easy to test, and the consultant can audit it. |
| B. Text similarity (embeddings over headlines) | Nearest neighbours on the headline/summary text | Later, as a "you might also compare with…" helper. On its own it is hard to explain and matches on wording rather than economics. |
| C. LLM judges similarity | LLM picks the similar events | Not as the primary matcher: it isn't repeatable and is hard to audit. Fine for *suggesting* tags (F5.3). |

### 4.2 Event taxonomy (v1 draft)

Types are chosen so that **past occurrences can be listed objectively**.
Each one has an official calendar or can be detected from stored data, so
the library doesn't depend on someone remembering events.

| Type | Tags | Source for the past list |
|---|---|---|
| `rbi_policy` | direction: cut / hike / hold; size_bps; stance change | RBI MPC decision dates (about 6 a year) |
| `fed_policy` | cut / hike / hold; size_bps | FOMC decision dates |
| `union_budget` | (optional: capex-heavy, LTCG/STT change) | Budget dates |
| `election_result` | national / state; outcome vs expectation | ECI result dates |
| `oil_shock` | up / down; size % | Curated (or detected from a crude series, if we add one) |
| `geopolitical_conflict` | region; involves an oil producer y/n | Curated |
| `global_risk_off` | trigger (bank failure, pandemic, …) | Curated |
| `sector_regulation` | sector; positive / negative | Curated (SEBI, RBI, ministry notices) |
| `company_shock` | issuer, group; kind (fraud allegation, default, downgrade) | Curated; later rating-action feeds |
| `market_drawdown` | Nifty 500 one-day fall ≥ X% | **Detected** from stored `index_prices` |
| `rating_action` | issuer; up / down; notches | Rating-agency releases (later feed) |

The 9 hand-picked events in `impact/historical.py` (`HISTORICAL_EVENTS`)
become the first entries in this library.

### 4.3 Matching and ranking

For a new event E with type T:

1. Candidates are library events of type T that have at least 20 trading
   days of price data after them (enough history to measure).
2. Score = number of matching tags, with the most important tags weighted
   (direction counts most: a rate *cut* is never "similar" to a *hike*).
   A per-type rule set says which tags are **required** (e.g. `direction`
   for `rbi_policy`) and which only affect ranking.
3. **De-duplicate overlapping events.** Events whose measurement windows
   overlap (e.g. Ukraine invasion 21 Feb 2022 and the oil spike 21 Feb
   2022) are grouped into one, so a single market episode isn't counted
   twice. Within a group the closer match is kept.
4. The consultant can **exclude** a precedent ("not comparable: this was
   during COVID") or **add** one by hand. Each change is recorded in the
   audit log and the summary is recalculated. This keeps a person in
   charge of what counts as similar (§9.2).

The match reasons are shown for each precedent ("same type, same
direction, size 25 bps vs 50 bps").

---

## 5. Measuring what happened ("families")

### 5.1 Families

A "family" is a group of instruments with a stored daily price series. All
of them already come from the free end-of-day sources in `marketdata/`:

| Family group | Series | Already stored? |
|---|---|---|
| Asset class | Equity = Nifty 500; Debt = Nifty 10 yr Benchmark G-Sec; Gold = gold ETF NAV (`gold_proxy`) | Yes |
| Sector | The 14 sectoral indices in `classify.SECTOR_INDEX` | Yes |
| Market cap | Nifty 50, Nifty Midcap 150, Nifty Smallcap 250 | Index closes are stored for every NSE index; these just need adding to the family list |
| **MF category** (P1) | Median daily NAV return of all Regular-plan schemes in an AMFI category (e.g. "Small Cap Fund", "Gilt Fund") | Needs the AMFI NAV history backfill, which hasn't yet been tested against the live AMFI site |
| The client's own holdings | Each holding's own price/NAV series | Yes (`prices`) |

MF categories are probably the most useful family for an MFD's book, since
most of it is in mutual funds. They are P1 because they depend on the AMFI
history backfill.

### 5.2 Event study method

For each precedent P and each family F:

- **Day 0** = the first trading day on which the market could react. If the
  event was announced after 3:30 pm IST, or on a holiday, day 0 is the next
  trading day. So each library event stores `announced_at` (date plus
  pre-market / intraday / post-market), not just a date.
- **Baseline** = the close on the trading day *before* day 0.
- **Horizons**: +1, +5, +20 trading days (to be confirmed with the
  consultant, CLIENT_QUESTIONS.md P4).
- **Return** = close at day 0 + h, divided by the baseline close, minus 1,
  from unadjusted index closes. Indices don't need split adjustment.
  Individual stocks go through `analytics/adjust.py`.
- **Excess return** = family return minus Nifty 500 return over the same
  window. This separates "IT fell because the whole market fell" from "IT
  fell more than the market". Both are shown; excess is the default view
  for sectors.

### 5.3 Summary statistics per family × horizon

| Stat | Definition |
|---|---|
| N | Number of precedents with data for this family at this horizon |
| Lower in X of N | Count with return < 0 (and the same for excess return) |
| Median, range | Median, min and max return |
| Normal rate | Share of *all* h-day windows since 2020 in which the family was lower, so the result has something to compare against |
| Interval (shown in a tooltip) | Wilson 90% interval on X / N, so the user can see how wide "7 of 9" really is |

Results are not tested for statistical significance: with N under 30 that
would give false precision. The interval and the normal rate show the same
uncertainty in plain terms.

### 5.4 Impact on clients

Reuse the existing shock engine (`impact/shocks.py`). Turn the precedents'
**median** and **worst** moves into a list of shocks, one per family
(sector filter plus a `not_sector` market move, as `real_shock` already
does), then run `book_impact`. The output is a range:

> If this went like the median past event: −₹1.2 L across 5 clients.
> Like the worst past event: −₹4.8 L.

This is a scenario like any other on the Scenarios page, labelled as
"based on past events", and it never comes with suggested trades.

---

## 6. Data model changes

```
HistoricalEvent  (replaces the hard-coded HISTORICAL_EVENTS list)
  id, type, title, summary, source_url
  announced_on (date), announced_session (pre | intraday | post)
  tags JSON          {"direction": "cut", "size_bps": 25, "sector": "...", "region": "..."}
  origin             curated | calendar | detected | from_event (promoted from Event)
  group_id           overlap group (§4.3 step 3)
  notes, created_at

Event  (existing)
  + type             taxonomy type (nullable for old events)
  + match_tags JSON  same shape as HistoricalEvent.tags
  (`tags` stays as the shock definition)

PrecedentOverride
  event_id, historical_event_id, action (exclude | include), reason, created_at

EventStudyCache
  historical_event_id, family, horizon, ret, excess_ret, computed_at
  (keyed so it can be rebuilt any time from prices/index_prices)
```

Once an `Event` is about 20 trading days old it can be **promoted** into
the library (the "aged event" logic already in `marketdata/refresh.py`
that fills in `actual_tags`), so the library grows over time.

---

## 7. API and UI

**API (FastAPI, `api/app.py`)**

- `GET /api/events/{id}/precedents`: matched past events with match
  reasons, the family × horizon summary table, and the normal rates.
- `POST /api/events/{id}/precedents/overrides`: exclude or include a
  precedent.
- `GET /api/events/{id}/precedents/chart?family=...`: each precedent's
  path for one family, aligned on day 0 and rebased to 100. This reuses
  `_rebase` / `family_series`.
- `POST /api/events/{id}/precedents/scenario?basis=median|worst`: client
  impact (§5.4).
- `GET/POST /api/library`: list, add and edit library events (Settings →
  Event library).

**UI (Events page → event detail → new "Past similar events" panel)**

1. A line at the top: "Matched 9 past events of type *Oil shock (up)* since
   2020", with the disclaimer.
2. Precedent list: date, title, match reasons, and an exclude toggle.
3. Family table: rows are families, columns are horizons. Each cell shows
   "lower 7/9 · median −4.1%", with the normal rate in grey underneath.
   Cells are coloured by median return on a diverging scale (not by rank).
   Cells with N < 5 are shown as "–".
4. Chart: precedent paths for the selected family, one thin line each,
   with the median path in bold, aligned to day 0.
5. "See client impact" opens the Scenarios page with the median/worst
   shock already applied.

Asset-class rows use the fixed colour slots (equity blue, debt orange,
gold yellow).

---

## 8. Phases

| Phase | Contents | Depends on |
|---|---|---|
| **P0a** | Library table + taxonomy; migrate `HISTORICAL_EVENTS`; seed `rbi_policy`, `fed_policy`, `union_budget`, `market_drawdown` from calendars and stored data | Index history back to 2020 (`kosh history --years 6`) |
| **P0b** | Matching, overlap groups, event-study maths, summary stats, normal rates; API | P0a |
| **P0c** | Event detail panel, chart, overrides, client-impact link | P0b |
| P1 | MF-category families; promote aged events into the library; LLM-suggested type/tags (F5.3) | AMFI NAV history backfill verified |
| P2 | Text-similarity suggestions; automated feeds triggering precedents (F5.1) | F5.1 feeds |

**Tests (backend):** event-study returns on a synthetic price series
(including holidays and a post-market announcement); overlap grouping;
required-tag matching (a cut never matches a hike); Wilson interval and
normal rate on known inputs; the N < 5 cut-off; and a **wording test** that
fails if any precedent API text contains banned words (§2).

---

## 9. Open questions for the consultant

Kept in [`CLIENT_QUESTIONS.md`](../CLIENT_QUESTIONS.md) §1 (P1–P11), next to the README.

---

## 10. Known limitations (to show in the UI help text)

- **Small samples.** Most event types have 5 to 30 occurrences since 2020.
  The UI shows N everywhere for this reason.
- **No two events are the same.** The same type of event can happen in
  very different market conditions. The exclude toggle and the match
  reasons let the consultant judge this.
- **End-of-day data only.** Reactions within the day aren't measured.
- **Survivorship in indices.** Sector indices change their members over
  time. That's acceptable for a family-level view and is noted in the help
  text.
