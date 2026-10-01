# 17 — LLM evaluation basics

## What is LLM evaluation?
Measuring whether an AI system's **answers are good**, not just whether its **code runs**. For us: given a
trip request, is the itinerary grounded in real research, does it fit the traveller, is it complete, and is it
honest about what it doesn't know?

## Why unit tests are not enough
Our 260+ tests use **fake** models that return fixed JSON. They prove the *code around the model* is correct:
the validator rejects unknown ids, the budget adds up, errors map to status codes. They can't tell us whether
**Gemini** will:

- schedule a sensible day or a random one,
- write descriptions faithful to the sources,
- choose places that suit a vegetarian family,
- mention a famous waterfall the sources never verified.

**Code tests can all pass while the product gives poor answers**, because the part that varies (model
output on real, changing web data) isn't in the tests. Evaluation runs the real model on realistic inputs and
scores the outputs.

## Three kinds of checking

| | Deterministic unit tests | Integration tests | LLM evaluation |
|---|---|---|---|
| What runs | one function | many components, fakes for external services | the real pipeline + real model |
| Inputs | hand-made | hand-made | realistic dataset of requests |
| Output | exact | exact | variable: differs run to run |
| Check | `assert x == y` | `assert` on shape and flow | **scores** (0–1) against thresholds |
| Cost / speed | free, ms | free, ms | API cost, seconds per case |
| When | every commit | every commit | before releases, after prompt/model changes |
| In this repo | `tests/unit` | `tests/integration`, `tests/api` | `evaluation/` |

## The qualities we evaluate, with travel-planner examples

| Quality | Question | Good example | Bad example | How we measure |
|---|---|---|---|---|
| **Grounding** | Does every scheduled place come from verified research? | Day 1 visits `A1 Baga Beach` (S2) | `place_id: "A99"`, unknown | code: `entity_grounding` |
| **Hallucination resistance** | Does any text name an unverified place? | "Free time near your hotel" | "…then head to Imaginary Palace" | code: `unsupported_places` |
| **Faithfulness** | Are the claims in descriptions supported by the evidence? | "17th-century fort" (source says so) | "UNESCO site with a sound-and-light show" (source doesn't) | LLM judge: DeepEval `FaithfulnessMetric` |
| **Relevance** | Does the plan match the request? | beaches + seafood for a beach/food couple | museums only for a beach trip | code: `preference_match` (coarse) + judge: `preference_alignment` |
| **Completeness** | Is everything asked for present? | 4 days numbered 1–4, dates, budget lines, sources | 3 days for a 4-day request | code: `completeness` |
| **Consistency** | Does it contradict itself or its numbers? | total = sum of lines | "₹25,630 total" but lines add to ₹24,000 | code: `budget_constraint`; judge: `itinerary_coherence` |
| **Constraint adherence** | Pace, group size, diet, no repeats? | ≤ 3 activities/day when relaxed; 2 rooms for 4 | 6 activities on a relaxed day | code: `constraint_adherence` |
| **Safety / honesty** | Does it admit uncertainty? | "Jain options not confirmed by sources" | claims a restaurant is Jain-friendly without evidence | code (dietary check) + judge (`usefulness`) |

## The rule of thumb used in this project
- **If a question has one correct answer that code can compute, use code.** Counting days, checking ids,
  adding money. An LLM judge would be slower, cost money, and sometimes be wrong.
- **If it needs judgement, use an LLM judge**, and treat its score as a noisy signal: coherence, usefulness,
  preference fit, faithfulness of free text.

## BEGINNER EXPLANATION
Unit tests check that the kitchen equipment works. Evaluation tastes the food. You need both: perfect ovens
don't guarantee a good meal, and a good meal one day doesn't mean the oven thermostat is correct.
