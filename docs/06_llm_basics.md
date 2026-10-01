# 06 — LLM basics (what you need before reading the AI code)

This chapter has no project code. It explains the ideas that `app/llm/`, `app/prompts/` and
`app/research/grounding.py` are built on. Every concept ends with **"In this project"**.

## What is an LLM?

**Simple:** a program that has read a huge amount of text and learned to continue text in a plausible way.
You give it text (a *prompt*), and it writes more text (a *completion*).

**Analogy:** an extremely well-read assistant with a perfect memory for *how things are usually said*, but
no access to today's news, and a habit of answering confidently even when unsure.

**Technical:** a neural network (a *transformer*) trained to predict the next *token* given all previous
tokens. Generation repeats that prediction token by token. Chat models are further trained to follow
instructions and hold a conversation made of *messages* with roles (system, user/human, assistant).

**In this project:** Gemini (`gemini-2.5-flash`) reads search results and writes structured JSON describing the
places in them (`app/llm/`, `app/prompts/research_prompt.py`).

## Tokens

A *token* is a chunk of text, often part of a word ("Calangute" might be 3 tokens). Models have a maximum
number of tokens they can read at once (the *context window*), and APIs bill per token, input and output
separately.

**In this project:** `SEARCH_MAX_CONTENT_CHARS` (1200) and `SEARCH_MAX_RESULTS` (5) cap how much web text
enters the prompt, which bounds cost. The response's `metadata.input_tokens` / `output_tokens` report what was
used when the provider says so. They are `null` (unknown), never `0`, when it doesn't.

## Prompt and context

The *prompt* is everything the model receives. The *context* is the information inside the prompt that the
model may use. A model only "knows" two things: what it memorised in training (frozen at a cutoff date,
unverifiable) and what is in the context (current and checkable).

**In this project:** we put the search results *into the context* and instruct the model to use only them.
That is the whole idea of **grounding** (and of RAG, retrieval-augmented generation).

## Messages and roles

- **system**: standing instructions (who you are, the rules). In our app this message never contains user
  or web text.
- **human/user**: the task and the data.
- **assistant/AI**: the model's reply.

**In this project:** `RESEARCH_PROMPT` has a system message (role, rules, constraints) and a human message
(trip context, sources, task). See `docs/09_research_pipeline.md` for a line-by-line explanation.

## Temperature

A dial for randomness when picking the next token. `0` means always pick the most likely token (more
repeatable); higher values mean more variety (more "creative").

**In this project:** extraction uses `RESEARCH_TEMPERATURE=0.0`, because copying facts from sources needs no
creativity. The itinerary planner uses a little more (`LLM_TEMPERATURE=0.3`).
Temperature 0 makes output *more* repeatable, not guaranteed identical.

## Structured output

By default an LLM writes prose. Code needs data. **Structured output** means requiring the reply to be JSON
matching a schema. It has two halves, and we use both:

1. **Constrain** generation: send the JSON Schema to the API (`response_json_schema` for Gemini) so the model
   is steered toward valid JSON.
2. **Verify** the result: parse and validate with Pydantic anyway, because constraints are not a guarantee.

**In this project:** `ResearchExtraction` (in `app/schemas/extraction.py`) is the schema; `StructuredLLM`
(`app/llm/client.py`) does both halves and retries once with error feedback if validation fails.

## Hallucination

**What:** fluent, confident output that is false. For a travel app: a restaurant that closed in 2023, a hotel
that never existed, a price from memory, invented opening hours.

**Why it happens:** the model is trained to produce *plausible* text, not *true* text. When the context lacks
an answer, the most plausible continuation is often a made-up one. Famous places are especially risky: the
model "knows" Dudhsagar Falls is in Goa and may attach it to a source that never mentions it.

**How we reduce it** (never "eliminate"; see `docs/10_hallucination_control.md`):
fresh search results in the context, citations to numbered sources, structured output, code that checks
every cited name and price against the source text, explicit uncertainty notes, and no estimated prices.

## Common mistakes beginners make with LLMs

| Mistake | Why it hurts | What this project does instead |
|---|---|---|
| Trusting output because it is fluent | Fluency ≠ truth | Verify against sources in code |
| Asking the LLM to do arithmetic | Unreliable with numbers | Budget is deterministic code (`app/planning/budget.py`) |
| Parsing prose with regexes | Breaks on wording changes | Structured output + Pydantic |
| Putting user/web text in the system prompt | Easier prompt injection | System prompt is fixed text |
| Unlimited retries on bad output | Unbounded cost | 1 output retry, then a clear error |
| Logging full prompts with keys or personal data | Leaks | Keys are `SecretStr`; prompts are not logged |
