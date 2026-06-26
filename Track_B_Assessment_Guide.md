# Track B (AI Applications) — Assessment Guide

A practical, day-by-day plan for the Buguard "Asset Management System" internship task, plus the technologies to learn and how to learn them fast enough to ship in one week.

---

## 1. What you're actually building

Quick recap, pulled straight from the task doc, so the plan below makes sense:

- A **small** FastAPI service — just enough to bulk-import the sample asset dataset and expose your analysis endpoints. Persistence in PostgreSQL.
- A **mandatory LangChain layer** with four working capabilities:
  1. **Natural-language asset query** — turn a plain-English question into a structured query over the asset data.
  2. **Risk scoring & summarization** — score an asset/group and summarize the risk (expired/expiring certs, exposed sensitive services, EOL tech).
  3. **Automated enrichment & categorization** — classify a new/raw asset (environment, category, criticality) and write enrichment back to metadata.
  4. **Natural-language report generation** — readable inventory/risk report over the dataset or a filtered subset.
- Must guard against the model **inventing assets that aren't in the data** — grounding is graded explicitly.
- Deliverables: GitHub repo, `docker-compose.yml`, README (setup, env vars, design decisions/assumptions, API docs, test instructions, example prompts + outputs).

**Where the points are** (Track B rubric, out of 100): LangChain features = 40, LLM integration quality (prompting, structured output, grounding, guardrails) = 20. That's **60% of your score in the AI layer**, not the API. The plan below allocates time accordingly — the API is deliberately the smaller half of the work.

---

## 2. Step-by-step plan

Treat these as effort-blocks, not literal calendar days — compress or stretch depending on your pace. The order matters more than the timing: get a thin, real pipeline (import → real Postgres rows) working before you write a single LangChain prompt, otherwise you have nothing to ground the LLM against.

### Day 0 (a few hours) — Setup & design
- Init the repo, GitHub remote, `.gitignore`, `.env.example`.
- Stand up `docker-compose.yml` with two services: `app` (FastAPI) and `db` (postgres:16). Confirm `docker compose up` boots both and the app can reach the DB.
- Design the asset schema from Section 3 of the task: one `assets` table (id, type, value, status, first_seen, last_seen, source, tags, metadata as JSONB) and one `relationships` table (id, from_asset_id, to_asset_id, relationship_type). Add a unique constraint on `(type, value)` — this is what makes dedup possible later.
- Decide your merge/dedup strategy and your LLM provider now, in writing (goes straight into the README's "assumptions" section later).

**Done when:** `docker compose up` gives you a running FastAPI app and an empty Postgres schema.

### Day 1 — Minimal ingest API + the messy-data edge cases
- Build `POST /import` (bulk JSON ingest of the sample dataset).
- Implement **upsert-based dedup**: match on `(type, value)`; on re-import, update `last_seen`, merge `tags` (union), merge `metadata` (your choice of strategy — e.g. newer source wins per-key, documented in README).
- **Idempotent imports**: running the same file twice → zero new rows, only `last_seen` bumps.
- **Re-appearing assets**: if a `stale`/`archived` asset shows up again, flip it back to `active`.
- **Malformed/partial records**: validate per-record (Pydantic), collect failures with reasons, continue the batch — never let one bad record 500 the whole import. Return `{imported, updated, failed: [...]}`.
- Build one `GET /assets` with pagination (limit/offset or cursor) and basic filters (type, status, tag) — you need this to feed the LangChain layer real data later.

**Done when:** you can import the sample dataset twice and get the same row count both times, and a deliberately broken record in the batch doesn't kill the import.

### Day 2–4 — The LangChain layer (this is most of your grade)
Do these in order — each one is easier once the previous one's plumbing exists.

**Day 2: NL query + risk scoring**
- *NL query*: don't let the LLM answer directly from "memory." Have it translate the question into a **structured filter object** (Pydantic schema: type, status, tag, date range, text-contains) via structured output, validate the fields against your actual enum/column values, then run a real SQL query against Postgres. The LLM never sees or invents asset IDs at this stage — it only produces a query spec.
- *Risk scoring*: fetch the real asset(s) from the DB first, pass that JSON into the prompt as context, and request a structured response (risk_score, severity, reasons[], summary) so the output is parseable and testable, not freeform prose.

**Day 3: Enrichment/categorization + start grounding the report generator**
- *Enrichment*: given a raw asset (value + whatever metadata exists), prompt for structured output (environment: prod/staging/dev, category, criticality, confidence) and write it back to the asset's `metadata` column.
- *Report generation*: pull the real filtered dataset first (reuse your query logic), then prompt the model to write a narrative report **only from the JSON you hand it**, instructing it to reference assets by the exact `id`/`value` strings provided.

**Day 4: Guardrails (don't skip this — it's explicitly graded)**
- After any LLM output that mentions asset IDs/values (report, summary), **validate every mentioned ID against the set you actually queried**. If the model references something not in that set, strip it, regenerate, or flag it — don't silently ship it.
- Handle ambiguous/out-of-scope NL queries gracefully (e.g., "I don't have data to answer that" rather than a guess).
- Wrap LLM calls with try/except for provider errors/timeouts and return clean error responses, not stack traces.

**Done when:** all four capabilities work end-to-end against real imported data, and you can demonstrate the model refusing or correcting itself when asked something the data doesn't support.

### Day 5 — Tests, docs, polish
- Unit tests for: dedup/upsert logic, the NL→filter translation (a handful of fixed example questions with known expected filters), and the grounding check (an injected "hallucinated" ID gets caught).
- Finalize the README: setup/run instructions, env vars, design decisions & assumptions, link to `/docs` (FastAPI's free OpenAPI UI), how to run tests, and — required for this track — **example prompts and their actual outputs** for all four capabilities.
- Make sure secrets are only in `.env.example` (with placeholder values), never committed.

### Day 6 (buffer) — Bonus, if time allows
Pick one, don't spread thin: turn the analysis layer into an agent that calls your own API as tools, add a small evaluation harness for output quality, add response caching, or stub out multi-tenant scoping (an `org_id` column + filtering everywhere).

---

## 3. Technologies to learn, by priority

| Priority | Technology | Why you need it |
|---|---|---|
| Critical | **FastAPI** | The API layer itself; gives you OpenAPI docs for free |
| Critical | **Pydantic v2** | Request/response validation *and* structured LLM output schemas — you'll use this constantly |
| Critical | **PostgreSQL + SQL basics** | System of record; JSONB for `metadata` |
| Critical | **SQLAlchemy or SQLModel** | Talk to Postgres from Python without hand-writing every query |
| Critical | **LangChain** (prompt templates, chains, structured output) | The mandatory analysis layer — this is 60% of your grade |
| Critical | **An LLM provider SDK** (Anthropic or OpenAI) | Whichever LangChain integration you pick; env-var key handling |
| Important | **Docker & Docker Compose** | Required deliverable: one-command `app + postgres` startup |
| Important | **pytest** | Core-logic tests (dedup, grounding, query translation) |
| Nice-to-have | **LangChain agents / tool-calling** | Only needed for the bonus "agent calls your API as tools" |
| Nice-to-have | **Alembic** | Migrations — fine to skip for a 1-week project and just use `create_all()`, mention that choice in your README |

You likely already know Python and Git given the internship context, so they're left off the table — but make sure your commit history is incremental and readable; it's explicitly mentioned in the rubric.

---

## 4. How to learn each one, fast

The honest constraint here is one week, so the goal isn't mastery — it's "enough to build the specific thing in Section 2, correctly." Skim the official quickstart for each, then learn the rest by building against your actual schema/dataset rather than working through a full course.

**FastAPI**
- Read: the official tutorial at fastapi.tiangolo.com — specifically "First Steps," "Path Parameters," "Request Body," "Query Parameters," and the "SQL (Relational) Databases" page, which shows the exact FastAPI + SQLAlchemy pattern you'll use.
- Skip: anything about templating/forms/websockets — not relevant here.

**Pydantic v2**
- Read: pydantic.dev's "Models" and "Fields" docs. You mainly need: defining a `BaseModel` with typed fields, `Enum` fields (for your `type`/`status` enums), and nested models (for `metadata`).
- This doubles as your LangChain structured-output schema later, so time spent here pays off twice.

**PostgreSQL / SQL**
- You don't need deep DBA knowledge. Know: `CREATE TABLE`, basic `SELECT ... WHERE ... LIMIT/OFFSET`, indexes, and how JSONB columns work, since `metadata` is JSON.
- If your SQL is rusty, postgresql.org's own tutorial (sections 1–4) covers exactly this in under an hour.

**SQLAlchemy or SQLModel**
- For a 1-week solo project, **SQLModel** (by the same author as FastAPI) is the faster path — it merges your Pydantic models and your DB tables into one class, less boilerplate. Docs: sqlmodel.tiangolo.com, read "Create a Table" through "Read and Update."
- If you'd rather use SQLAlchemy directly (more control, slightly more code), its official "ORM Quick Start" covers the same ground.

**Docker & Docker Compose**
- Read: docs.docker.com's "Compose" getting-started guide. You specifically need: a `docker-compose.yml` with a `db` service using the official `postgres` image plus volume + env vars, and an `app` service that `depends_on: db`.
- Test early — "it works on my machine but not in Compose" networking issues (using `localhost` instead of the service name `db` as the host) are the most common time sink here.

**LangChain — the core of this assessment**
LangChain has shifted in recent releases toward a unified docs site and a small set of high-level building blocks, so go straight to current material rather than older blog tutorials:
- Start at **docs.langchain.com** (Installation → Quickstart) for the current Python API: `init_chat_model` to connect to your provider, and the **LCEL pipe syntax** (`prompt | model | parser`) for chaining a prompt template into a model call.
- For all four of your capabilities, the feature that matters most is **structured output**: `model.with_structured_output(YourPydanticSchema)`, which returns a validated Pydantic instance instead of free text. This is also your main anti-hallucination tool — if the LLM has to fill in a typed schema rather than write prose, it's much easier to validate its claims against your real data afterward.
- If you want a guided, free walkthrough rather than just docs, **LangChain Academy** (academy.langchain.com) runs an official "LangChain Essentials" course covering exactly this path: messages, prompts, structured output, and tools.
- You do **not** need LangGraph or the full agent framework (`create_agent`) for the four mandatory capabilities — those are chains, not agents. Only reach for agent/tool-calling concepts if you attempt the bonus "agent calls your own API" stretch goal.

**LLM provider SDK (Anthropic or OpenAI)**
- Pick one based on what you have API access to. Read just the "quickstart"/"first request" page of whichever you choose — LangChain's `init_chat_model` abstracts most of the rest away.
- Set up `.env` + `python-dotenv` (or FastAPI's own settings pattern) immediately so you never hardcode a key, and add `.env` to `.gitignore` on day 0.

**pytest**
- Read: pytest's "Getting Started" page. You need: a test file per module, `assert` statements, and FastAPI's `TestClient`/`httpx` for hitting your endpoints in tests. That's sufficient for the core-logic tests this task expects.

---

## 5. The grounding pattern, concretely

Since "guard against the model inventing assets" is explicitly graded, here's the shape of the pattern referenced in Sections 2 and 4 above:

```python
from pydantic import BaseModel

class QueryFilter(BaseModel):
    asset_type: str | None = None
    status: str | None = None
    tag: str | None = None
    value_contains: str | None = None

# 1. LLM only ever produces a filter, never an answer
filter_chain = nl_query_prompt | llm.with_structured_output(QueryFilter)
filter_obj = filter_chain.invoke({"question": user_question})

# 2. You run the REAL query — the LLM never sees asset data it didn't request
results = run_db_query(filter_obj)  # actual SQL/ORM call

# 3. Only now does the LLM see real rows, to summarize/report on them
report = report_chain.invoke({"assets": results})

# 4. Validate any IDs the model mentions in its output against `results`
real_ids = {r.id for r in results}
mentioned_ids = extract_ids(report)
assert mentioned_ids <= real_ids, "model referenced an asset not in the dataset"
```

The key idea: the LLM is never the source of truth for *which assets exist* — your database always is. The LLM only ever (a) translates intent into a query, or (b) summarizes rows you already fetched.

---

## 6. Suggested minimal repo layout

```
.
├── docker-compose.yml
├── .env.example
├── README.md
├── app/
│   ├── main.py              # FastAPI app, routes
│   ├── models.py            # SQLModel/SQLAlchemy table models
│   ├── schemas.py           # Pydantic request/response + LLM structured-output schemas
│   ├── db.py                 # engine/session setup
│   ├── ingest.py              # import + dedup/merge logic
│   └── ai/
│       ├── query.py          # NL → filter chain
│       ├── risk.py           # risk scoring & summarization chain
│       ├── enrich.py         # categorization/enrichment chain
│       └── report.py         # report generation chain + grounding check
└── tests/
    ├── test_ingest.py
    ├── test_query.py
    └── test_grounding.py
```

---

## 7. Pre-submission checklist

- [ ] `docker compose up` starts the app + Postgres with no manual steps
- [ ] `/import` is idempotent and survives malformed records
- [ ] All four LangChain capabilities work against real imported data, not hardcoded examples
- [ ] At least one guardrail test proves hallucinated IDs get caught
- [ ] README has: setup/run instructions, env vars, design decisions & assumptions, API docs link, test-run instructions, and example prompts + real outputs for all four capabilities
- [ ] No API keys or secrets committed (check `.env` is gitignored)
- [ ] Git history shows incremental, readable progress, not one giant commit
