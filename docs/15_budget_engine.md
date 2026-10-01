# 15 — The budget engine (Phase 11)

Files: [`app/planning/budget.py`](../app/planning/budget.py), [`app/planning/budget_rates.py`](../app/planning/budget_rates.py),
[`app/planning/pricing.py`](../app/planning/pricing.py), [`app/planning/rules.py`](../app/planning/rules.py)

## WHY deterministic code
A budget is a handful of multiplications and one sum. LLMs predict likely-looking text; they regularly get
multi-step arithmetic wrong and state the wrong total confidently. Code is always right about arithmetic,
costs nothing, runs in microseconds, and can **show its working** on every line.

## INPUT → OUTPUT
`TravelRequest` + assembled `Itinerary` + verified `ResearchResult` → `BudgetBreakdown` (one `BudgetLineItem`
per category with `amount`, `basis`, `detail`) + warnings (`OVER_BUDGET`, `BUDGET_INCOMPLETE`).

## LOGIC: where each number comes from

| Category | First choice: verified source price | Fallback |
|---|---|---|
| accommodation | chosen hotel's per-night rate × nights × rooms | developer default per room/night for the tier (per bed for hostels) → `estimate` |
| food | (not used; see below) | default per person per day for the tier → `estimate` |
| local transport | verified per-day local option × days × ⌈travellers/2⌉ | default per person per day → `estimate` |
| intercity transport | verified intercity fare for the group × 2 (return) | **unknown**: counted as 0, `complete: false` |
| activities | sum of scheduled activities with verified prices | unpriced ones counted as 0 and listed in assumptions |
| miscellaneous | — | 10% of the subtotal → `estimate` |

Helper rules: `nights = days − 1`; `rooms = ⌈travellers / 2⌉` (double occupancy); unit parsing in
`price_for_group`: "per person" × travellers, "for two" × ⌈travellers/2⌉, "per night/day/room" × 1 (the
caller multiplies), unit not stated → assumed per person (over-estimating is the safer mistake) and labelled.

**Why food ignores restaurant prices:** the itinerary names *some* meals, not all three meals of every day.
Adding per-meal prices **and** a daily allowance would double-count.

### The fallback rates are placeholders, not data
`budget_rates.py` holds round numbers chosen by the developer (e.g. mid-range room ₹4,000/night, food
₹1,200/person/day). They are **not researched, not current, not destination-specific**, which is why every
use is labelled `basis: "estimate"` and written into `assumptions`. They exist only for INR; other currencies
get `unknown` rather than converted guesses. Tune them before relying on budgets.

## EXAMPLE: real output for the Goa walkthrough
(Goa fixtures; the hotel's price was removed during grounding and the train had no verified fare.)

| Category | Amount | Basis | How it was calculated |
|---|---:|---|---|
| accommodation | ₹12,000 | estimate | ₹4,000/room/night × 3 nights × 1 room(s) |
| food | ₹9,600 | estimate | ₹1,200/person/day × 2 × 4 days |
| local transport | ₹1,600 | source | scooter rental: ₹400/day × 4 days × 1 (one per two people) (S5) |
| intercity transport | ₹0 | unknown | No verified fare found from Bengaluru. |
| activities | ₹100 | source | 1 activity price(s) from sources (Fort Aguada ₹50 × 2) |
| miscellaneous | ₹2,330 | estimate | 10% of subtotal ₹23,300 |
| **total** | **₹25,630** | | budget ₹25,000 → remaining −₹630, `within_budget: false`, `complete: false` |

Warnings produced: `OVER_BUDGET` ("exceeds the budget ₹25,000 by ₹630 (3%)") and `BUDGET_INCOMPLETE`
("Some costs are unknown and counted as 0, so the real total will be higher."). `quality.sourced_cost_ratio`
is 0.066: only 6.6% of this total comes from quoted prices, which tells the user how much to trust it.

## What it does NOT do (yet)
- Ask the LLM to re-plan when over budget (currently a warning; a "cheaper alternatives" repair round is a
  future improvement).
- Currency conversion, seasonal pricing, taxes.

## BEGINNER EXPLANATION
A calculator with a notebook: for every line it writes the sum it did and where each number came from
("from the hotel's web page" or "my rough default"). If it doesn't know a number at all, it writes "unknown"
and warns you, instead of making one up.
