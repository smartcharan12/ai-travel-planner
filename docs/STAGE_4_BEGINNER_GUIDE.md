# Stage 4 beginner guide: evaluation, observability, ELK, Docker

Read this before the detailed docs (17–22). Each idea: simple explanation → analogy → where it is in this project.

### 1. Why LLM evaluation is needed
Our tests use fake models, so they prove the *code* is right, not that *Gemini's answers* are good. Evaluation
runs the real model on realistic requests and scores the answers.
*Analogy:* testing the oven vs tasting the dish. → `evaluation/`, `docs/17`.

### 2. What DeepEval does
A Python library that turns "is this answer good?" into test-like checks: test cases, metrics with scores and
thresholds, pass/fail, reports. → `evaluation/metrics/`, `python -m evaluation.runner`.

### 3. What an evaluation dataset is
A fixed list of realistic inputs used every time, so results are comparable across prompt or model changes.
*Analogy:* the same exam paper for every student. → `evaluation/datasets/travel_cases.json` (10 trips:
Goa, Hyderabad, Jaipur, Delhi, Bengaluru).

### 4. What an evaluation metric is
A function: (input, output, evidence) → score 0–1 + reason. Compared to a threshold → pass/fail.
*Example:* `budget_constraint` = 1.0 if all lines add up to the total and overruns are flagged.

### 5. What LLM-as-a-judge means
Asking another LLM to grade an answer against a rubric ("is this plan coherent?"). Useful for qualities with no
formula; biased, sometimes inconsistent, and it costs money, so it's a signal, not the truth.
*Analogy:* a second opinion from a knowledgeable but opinionated colleague. → `evaluation/metrics/judge.py`.

### 6. Why deterministic evaluation is also necessary
Some questions have one right answer: "are there 4 days?", "does ₹12,000 + ₹9,600 + … = ₹25,630?", "is A99
a verified place?". Code answers them exactly, instantly and for free. Never ask an LLM to check arithmetic.
→ `evaluation/metrics/deterministic.py`.

### 7. What observability means
Being able to understand what the running system did, after the fact, from the data it emits.
*Analogy:* a plane's flight recorder and cockpit gauges. → `app/observability/`.

### 8. Logs vs metrics vs traces
- **Logs:** a diary entry per event ("Gemini took 2.3 s for request 5ece"). → JSON events.
- **Metrics:** counters and averages ("18% of plans needed repair today"). → `/api/v1/metrics`.
- **Traces:** a timed path of one request across components. → partially: events share a `request_id`
  (no tracing system yet).

### 9. Why JSON logs
Machines can filter fields (`status >= 500`, `destination: "Goa"`) instead of guessing from sentences.
*Analogy:* a spreadsheet row instead of a handwritten note.

### 10. What Elasticsearch is
A database/search engine for JSON documents; finds and counts matching documents across millions in
milliseconds. *Analogy:* a library with an instant index of every word in every book. → stores our log lines.

### 11. What Logstash is
A pipeline that reads data from somewhere, cleans it, and sends it somewhere else.
*Analogy:* a mail-sorting room. → reads the API's log file, fixes field types, removes anything secret-looking,
sends to Elasticsearch.

### 12. What Kibana is
A website for searching and charting Elasticsearch data. *Analogy:* the library's reading room with charts on
the wall. → http://localhost:5601: saved searches like "LLM call failures".

### 13. How they connect
API → JSON lines in a shared file → Logstash tails the file → Elasticsearch indexes each line → Kibana queries
Elasticsearch. The API never waits for any of them.

### 14. What Docker is
A tool that packages an app with everything it needs (Python, libraries, code) into an **image** that runs the
same on any machine. *Analogy:* a shipping container: the crane doesn't care what's inside.

### 15. What a container is
A running instance of an image, isolated from the rest of the machine (own filesystem, process list, network).
Ours run as a non-root user and hold no secrets; keys are given at start-up.

### 16. What Docker Compose is
One file describing several containers and how they connect, started with one command.
*Analogy:* an orchestra score vs individual parts. → `docker-compose.yml`: api, frontend, (+ elasticsearch,
logstash, kibana with `--profile elk`).

### 17. Why these matter in this project
- **Evaluation** is the only way to know whether prompt or model changes made plans better or worse.
- **Observability** answers "why was it slow / wrong / expensive?" for a real request, and "how often does
  repair happen?" overall.
- **ELK** makes those logs searchable across containers and restarts.
- **Docker** makes "works on my machine" true everywhere, and is the unit Kubernetes runs in Stage 5.

### What was and was not verified in Stage 4
| Item | Status |
|---|---|
| Grounding fix, logging, metrics, evaluation code | built and tested offline |
| Demo evaluation | run (pipeline mechanics only) |
| Live evaluation, LLM judge | NOT RUN: API keys not available |
| Docker build, compose, ELK | NOT RUN: Docker not installed; configuration statically tested |
