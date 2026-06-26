# DarkAtlas Asset Management System

A self-contained module of the DarkAtlas Attack Surface Monitoring platform — built as the **Track B (AI Applications)** internship assessment.

## What it does

- **Bulk asset import** with upsert-based deduplication, tag/metadata merging, and graceful handling of malformed records.
- **Four LangChain-powered AI capabilities** over the real imported data:
  1. Natural-language asset querying (grounded — LLM never invents asset IDs)
  2. Risk scoring & summarization (structured output, pre-computed hints for expired certs / sensitive ports / EOL tech)
  3. Automated enrichment & categorization (environment, category, criticality written back to DB)
  4. Natural-language report generation with post-generation hallucination detection
- **PostgreSQL persistence** via SQLModel (SQLAlchemy + Pydantic).
- **OpenAPI docs** at `/docs` (FastAPI built-in).
- One-command startup: `docker compose up`.

---

## Quick Start (Docker — recommended)

### Prerequisites
- Docker + Docker Compose installed.
- A Groq API key from [console.groq.com](https://console.groq.com).

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd asset-management-system
cp .env.example .env
# Edit .env and set GROQ_API_KEY=your_actual_key
```

### 2. Start everything

```bash
docker compose up
```

Both services start: `db` (PostgreSQL 16) and `app` (FastAPI on port 8000).  
The app creates its tables automatically on first boot.

### 3. Import the sample dataset

```bash
curl -X POST http://localhost:8000/import \
  -H "Content-Type: application/json" \
  -d @data/sample_assets.json
```

Response: `{"imported": 34, "updated": 0, "failed": [{"index": 35, ...}]}`  
(The dataset includes one intentionally malformed record to demonstrate graceful failure.)

### 4. Open API docs

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive OpenAPI UI.

---

## Local Development (without Docker)

### Prerequisites
- Python 3.12+
- PostgreSQL 16 running locally (or use Docker just for the DB)

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
cp .env.example .env
# Edit .env — set DATABASE_URL to point at your local Postgres and set GROQ_API_KEY
```

Start the DB only via Docker:
```bash
docker compose up db -d
```

Run the API:
```bash
uvicorn app.main:app --reload
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `POSTGRES_USER` | Docker only | `assetuser` | Postgres username |
| `POSTGRES_PASSWORD` | Docker only | `assetpass` | Postgres password |
| `POSTGRES_DB` | Docker only | `assetdb` | Database name |
| `GROQ_API_KEY` | Yes | — | Groq API key (from console.groq.com) |
| `LLM_MODEL` | No | `llama-3.3-70b-versatile` | Groq model name |

> **Security note**: Never commit `.env`. It is in `.gitignore`. Use `.env.example` (placeholder values only) for sharing the template.

---

## API Endpoints

### Asset Management

| Method | Path | Description |
|---|---|---|
| `POST` | `/import` | Bulk import assets (JSON array) |
| `GET` | `/assets` | List assets with filters + pagination |
| `GET` | `/assets/{id}` | Get single asset |
| `GET` | `/assets/{id}/relationships` | Get relationships for an asset |

**GET /assets query parameters:**
- `type` — filter by asset type: `domain`, `subdomain`, `ip_address`, `service`, `certificate`, `technology`
- `status` — filter by lifecycle: `active`, `stale`, `archived`
- `tag` — filter by tag label (e.g. `prod`, `expired`)
- `value_contains` — substring search in asset value
- `limit` / `offset` — pagination (default limit=20, max=200)

### AI Analysis

| Method | Path | Description |
|---|---|---|
| `POST` | `/ai/query` | Natural-language asset query |
| `POST` | `/ai/risk` | Risk scoring & summarization |
| `POST` | `/ai/enrich/{asset_id}` | Automated enrichment & categorization |
| `POST` | `/ai/report` | Natural-language report generation |

---

## Running Tests

```bash
# Using virtual environment (recommended — avoids system package conflicts)
.venv\Scripts\activate
python -m pytest tests/ -v

# Or with Python directly (if no environment conflicts)
python -m pytest tests/ -v
```

Test coverage:
- `tests/test_ingest.py` — dedup/upsert logic, idempotency, stale reactivation, malformed record handling, metadata merge
- `tests/test_query.py` — filter application, NL→filter translation (mocked LLM), out-of-scope queries
- `tests/test_grounding.py` — hallucination detection, ID stripping, value extraction from report text

---

## Design Decisions & Assumptions

### Deduplication strategy
- **Unique constraint on `(type, value)`** — this is the canonical identity of an asset.
- **Tag merge**: union (all unique tags from both imports are preserved).
- **Metadata merge**: newer-source-wins per key (incoming values overwrite existing ones; existing keys not in incoming are preserved).
- **Re-appearing stale/archived assets**: status is flipped back to `active` automatically.
- **Idempotent**: re-importing the same dataset produces zero new rows (only `last_seen` is updated).

### LLM Provider choice
- **Groq + LLaMA 3.3 70B**: chosen for excellent structured output support, fast inference, and free-tier availability. The integration is via `langchain-groq`, which wraps LangChain's standard interface — swapping to OpenAI/Anthropic requires changing one env var.

### Migrations
- **No Alembic**: `SQLModel.metadata.create_all()` on startup. Acceptable for a 1-week project scope; documented here. A production system would use Alembic.

### Grounding (hallucination prevention)
The LLM is never the source of truth for which assets exist. The pattern used throughout:
1. LLM translates NL intent → structured filter (no asset IDs produced).
2. We run a real SQL query.
3. Only then does the LLM see real rows.
4. After report generation, every asset ID mentioned by the model is validated against the queried set — hallucinated IDs are stripped and flagged in the response.

### Asset schema
- UUID primary keys (safe to expose in APIs, globally unique).
- `tags` and `metadata` stored as JSON columns (PostgreSQL JSONB-compatible).
- `metadata_` used as the Python attribute name to avoid collision with SQLModel internals (maps to `metadata` column in DB).

### Relationship hints
The import payload supports two convenience fields:
- `parent`: external ID of a parent domain (creates a `subdomain_of` relationship)
- `covers`: external ID of a domain/subdomain a certificate covers (creates a `secures` relationship)

---

## Example Prompts and Outputs

### 1. Natural-language query

**Request:**
```json
POST /ai/query
{"question": "Show me all expired certificates on production subdomains"}
```

**Response:**
```json
{
  "out_of_scope": false,
  "filter_used": {"asset_type": "certificate", "tag": "prod"},
  "results": [
    {
      "id": "...",
      "type": "certificate",
      "value": "CN=api.example.com",
      "metadata": {"expires": "2025-01-02", "issuer": "Let's Encrypt"},
      ...
    }
  ],
  "total": 3
}
```

**Out-of-scope example:**
```json
POST /ai/query
{"question": "What is the weather in Cairo today?"}
```
```json
{
  "out_of_scope": true,
  "message": "This question is about weather conditions, which is outside the scope of asset data.",
  "results": [],
  "total": 0
}
```

---

### 2. Risk scoring

**Request:**
```json
POST /ai/risk
{"asset_ids": []}
```
*(empty = analyze all assets)*

**Response:**
```json
{
  "risk_assessment": {
    "risk_score": 72,
    "severity": "high",
    "reasons": [
      "CN=*.example.com wildcard certificate expired on 2024-06-01",
      "MySQL 5.7.32 is end-of-life since 2023-10-31",
      "Port 3306 (MySQL) exposed on 203.0.113.11 — sensitive database port",
      "Port 22 (SSH) exposed on 203.0.113.11",
      "PHP 7.2.0 is end-of-life since 2020-11-30"
    ],
    "summary": "The asset inventory contains two expired certificates, two end-of-life technologies, and multiple sensitive ports exposed on internet-facing IP addresses.",
    "recommendations": [
      "Renew the wildcard certificate CN=*.example.com immediately",
      "Upgrade MySQL 5.7 to 8.0+ (EOL since Oct 2023)",
      "Restrict port 3306 to internal network access only",
      "Upgrade PHP 7.2 to 8.2+ (EOL since Nov 2020)"
    ]
  },
  "assets_analyzed": 35,
  "asset_ids": ["...", "..."]
}
```

---

### 3. Automated enrichment

**Request:**
```json
POST /ai/enrich/{asset_id_for_payments.example.com}
```

**Response:**
```json
{
  "asset_id": "...",
  "asset_value": "payments.example.com",
  "enrichment": {
    "environment": "prod",
    "category": "payment gateway",
    "criticality": "critical",
    "confidence": 0.97,
    "reasoning": "The subdomain 'payments' strongly indicates a production payment processing endpoint. The metadata confirms pci_scope=true and the 'critical' tag is already present."
  },
  "tags_after": ["prod", "payments", "critical"],
  "metadata_after": {
    "service_type": "payment gateway",
    "pci_scope": true,
    "ai_enrichment": {
      "environment": "prod",
      "category": "payment gateway",
      "criticality": "critical",
      "confidence": 0.97,
      "reasoning": "..."
    }
  }
}
```

---

### 4. Report generation

**Request:**
```json
POST /ai/report
{
  "filter": {"asset_type": "certificate"}
}
```

**Response:**
```json
{
  "report": {
    "title": "Certificate Health Assessment Report",
    "executive_summary": "Analysis of 5 TLS certificates reveals 2 expired and 1 expiring-soon certificate, posing immediate risk to service availability and user trust.",
    "sections": [
      {
        "title": "Expired Certificates",
        "content": "Two certificates have expired: CN=api.example.com (expired 2025-01-02, issued by Let's Encrypt) and CN=*.example.com (expired 2024-06-01). These assets should be renewed immediately.",
        "referenced_asset_ids": ["<real-uuid-1>", "<real-uuid-2>"]
      },
      ...
    ],
    "key_findings": [
      "2 of 5 certificates are expired",
      "Wildcard certificate CN=*.example.com is a high-impact expiry affecting all subdomains",
      "Payments subdomain certificate (DigiCert EV) remains valid until 2027-03-01"
    ],
    "overall_risk_level": "high"
  },
  "grounding_validation": {
    "grounded": true,
    "hallucinated_ids": [],
    "flagged_sections": [],
    "total_assets_queried": 5,
    "asset_values_confirmed_in_text": ["CN=api.example.com", "CN=*.example.com"]
  }
}
```

---

## Project Structure

```
.
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── data/
│   └── sample_assets.json      # 35-record realistic dataset
├── app/
│   ├── main.py                 # FastAPI app + startup
│   ├── db.py                   # Engine + session dependency
│   ├── models.py               # SQLModel table definitions
│   ├── schemas.py              # Pydantic API + LLM output schemas
│   ├── ingest.py               # Bulk import + dedup logic
│   ├── routers/
│   │   ├── assets.py           # /import and /assets endpoints
│   │   └── ai.py               # /ai/* endpoints
│   └── ai/
│       ├── llm.py              # Groq LLM initialization
│       ├── grounding.py        # Hallucination validation utilities
│       ├── query.py            # NL → filter → SQL chain
│       ├── risk.py             # Risk scoring chain
│       ├── enrich.py           # Enrichment chain
│       └── report.py           # Report generation + grounding check
└── tests/
    ├── test_ingest.py
    ├── test_query.py
    └── test_grounding.py
```
