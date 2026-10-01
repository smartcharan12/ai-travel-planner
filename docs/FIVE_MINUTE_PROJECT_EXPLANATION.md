# The project in five minutes (spoken answer)

*Roughly 750 words, about five minutes at a normal pace. Headings are for you, not to be read aloud.*

**Problem.** "I built a travel itinerary planner, mainly to learn how to make an LLM application trustworthy and
operable, not just a demo. The core problem is that if you ask a chatbot to plan four days in Goa on ₹25,000, you
get a fluent plan with places it half-remembers and prices it made up. So my goal was: every place and every
price in the output should be traceable to a real source, or explicitly marked as an estimate or unknown."

**Architecture.** "It's a FastAPI backend with a Streamlit frontend. The backend runs a LangGraph workflow. The
API validates the request with Pydantic first, so bad input is rejected before any paid call. Then the workflow
does research, planning, validation and budgeting. The UI only talks to the API over HTTP."

**Search and the LLM.** "Research is a fixed set of five Tavily searches, run in parallel: destination info,
attractions, restaurants, hotels and transport. I deliberately didn't make it an autonomous agent that decides
whether to search, because every trip needs all five, and an agent that skips the hotel search is exactly how
invented hotels get in. Results are cleaned, deduplicated and numbered S1 to Sn. Gemini then extracts typed
entities, attractions, restaurants and so on, each citing a source id, using a JSON schema and Pydantic
validation."

**Grounding.** "The key step is grounding, and it's plain Python. For every extracted entity I check that the
cited source exists and that the name actually appears in that source's text. Prices must be quoted verbatim, and
the number must match the quote, otherwise the price is removed, never estimated. A typical catch is the model
'remembering' Dudhsagar Falls and citing a beach article that never mentions it."

**Planning, validation and repair.** "A second Gemini call arranges the verified places into days, but it can only
reference them by id, or use a fixed list of generic activities like free time or check-in. It doesn't write
titles or prices. Code generates the titles, dates and costs. That closed a gap I found in my own audit: the model
could previously put an unverified venue name in a free-text title. A deterministic optimizer fixes mechanical
issues like repeated attractions or overloaded days. A validator checks hard rules, including a check for
capitalised place names that aren't in the verified research. If there are errors, the plan goes back to Gemini
with the exact error list, at most twice; otherwise the API returns a clear error instead of a broken plan. The
budget is computed in code, because arithmetic is exactly what LLMs are unreliable at."

**Evaluation.** "Unit tests use fake models, so they can't tell you whether real answers are good. I added a
DeepEval suite with ten fixed trips across five cities. Seven metrics are deterministic: grounding, completeness,
budget arithmetic, constraints. Four are LLM-as-judge: faithfulness to the evidence, coherence, preference fit and
usefulness. I'm explicit that the judge is a noisy signal with self-preference bias, and that my thresholds are
initial engineering values. So far I've only run it in demo mode on invented data. It correctly flagged two cases
where interests weren't covered. I haven't run it against the real APIs yet."

**Observability.** "Every request gets an id, and every step emits a JSON log event: each search, each LLM call
with latency and tokens, each validation and repair. There are metrics that directly answer how often the first
draft is invalid and how often repair fixes it. Locally, logs go through Logstash into Elasticsearch and Kibana.
On GCP I'd rely on Cloud Logging, because running ELK on GKE would mean operating a stateful cluster for no gain."

**Docker, Kubernetes, GCP.** "The images are multi-stage and non-root. The Kubernetes manifests run two to six
API replicas with an HPA, separate liveness and readiness probes, because missing keys should stop traffic, not
cause restart loops. They also have read-only filesystems and a default-deny NetworkPolicy, and only the UI is
exposed. The GCP design uses GKE Autopilot, Artifact Registry, Secret Manager mounted as files, and Workload
Identity, so there are no JSON key files anywhere, including in GitHub Actions. CI runs lint, the 300 tests,
dependency auditing and manifest validation on every PR, and builds and scans images on main."

**Honesty and challenges.** "To be clear about status: the manifests pass strict schema validation and the
workflows pass actionlint, but I haven't actually run Docker, a cluster or GCP, and I haven't called the real
Gemini or Tavily APIs. I didn't have the environment or keys. The biggest technical challenges were making
grounding deterministic without a fragile blacklist, and keeping the LLM out of anything with a single correct
answer."

**Future work.** "Next I'd run it for real and measure latency and cost per plan, cache research per destination,
make repair target only the failing day, autoscale on in-flight requests rather than CPU since the service mostly
waits on Gemini, and add authentication before exposing it publicly."
