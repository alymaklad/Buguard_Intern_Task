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

> All outputs below are **real responses** captured live from the running app against the sample dataset.

---

### 1. Natural-language query — `POST /ai/query`

**Prompt:** *"Show me all production subdomains"*

```bash
curl -X POST http://localhost:8000/ai/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me all production subdomains"}'
```

```json
{
  "out_of_scope": false,
  "filter_used": {
    "asset_type": "subdomain",
    "tag": "prod",
    "out_of_scope": false
  },
  "results": [
    {
      "id": "27e4d372-2e4b-49f9-8c51-7ad9edfb218a",
      "type": "subdomain",
      "value": "api.example.com",
      "status": "active",
      "tags": ["api", "critical", "prod"],
      "metadata": { "service_type": "REST API" }
    },
    {
      "id": "2adb56d6-153f-4f28-9ec5-a8c85edb363e",
      "type": "subdomain",
      "value": "www.example.com",
      "status": "active",
      "tags": ["prod", "web"],
      "metadata": { "service_type": "web" }
    },
    {
      "id": "1ef1ec92-1167-412d-a3af-e6b3ed8831fa",
      "type": "subdomain",
      "value": "admin.example.com",
      "status": "active",
      "tags": ["prod", "admin"],
      "metadata": { "service_type": "admin panel" }
    },
    {
      "id": "a1cd3d7b-d313-4fe1-a70d-4abd9f309a5e",
      "type": "subdomain",
      "value": "payments.example.com",
      "status": "active",
      "tags": ["prod", "payments", "critical"],
      "metadata": { "service_type": "payment gateway", "pci_scope": true }
    }
  ],
  "total": 7
}
```

**Guardrail — out-of-scope query:** *"What is the weather today?"*

```json
{
  "out_of_scope": true,
  "message": "The question is about the weather, which is not related to asset data.",
  "filter_used": null,
  "results": [],
  "total": 0
}
```

---

### 2. Risk scoring — `POST /ai/risk`

**Prompt:** Analyze all assets (empty `asset_ids` = full dataset)

```bash
curl -X POST http://localhost:8000/ai/risk \
  -H "Content-Type: application/json" \
  -d '{"asset_ids": []}'
```

```json
{
  "risk_assessment": {
    "risk_score": 95,
    "severity": "critical",
    "reasons": [
      "Expired certificate: CN=api.example.com",
      "Expired certificate: CN=*.example.com",
      "Expired certificate: CN=admin.example.com",
      "Sensitive exposed service: 22/tcp (port=22, banner=openssh_8.2p1)",
      "Sensitive exposed service: 3306/tcp (port=3306, banner=mysql 5.7.32)",
      "Sensitive exposed service: 21/tcp (port=21, banner=vsftpd 3.0.3)",
      "Sensitive exposed service: 5432/tcp (port=5432, banner=postgresql 14.2)",
      "Stale asset: dev.example.com",
      "Stale asset: 192.168.1.50",
      "Stale asset: PHP/7.2.0",
      "End-of-life technology: MySQL/5.7.32",
      "End-of-life technology: PHP/7.2.0"
    ],
    "summary": "The organization has multiple expired certificates, sensitive exposed services, stale assets, and end-of-life technologies, posing a significant risk to its security posture.",
    "recommendations": [
      "Renew expired certificates",
      "Remove or update sensitive exposed services",
      "Investigate and update stale assets",
      "Update end-of-life technologies"
    ]
  },
  "assets_analyzed": 36
}
```

---

### 3. Automated enrichment — `POST /ai/enrich/{asset_id}`

**Prompt:** Enrich `payments.example.com`

```bash
curl -X POST http://localhost:8000/ai/enrich/a1cd3d7b-d313-4fe1-a70d-4abd9f309a5e
```

```json
{
  "asset_id": "a1cd3d7b-d313-4fe1-a70d-4abd9f309a5e",
  "asset_value": "payments.example.com",
  "enrichment": {
    "environment": "prod",
    "category": "web",
    "criticality": "critical",
    "confidence": 0.9,
    "reasoning": "The subdomain 'payments.example.com' is classified as 'critical' due to its association with payment processing and PCI scope, as indicated by the 'pci_scope' metadata and 'payments' tag. The 'prod' tag and the presence of a payment gateway service suggest a production environment."
  },
  "tags_after": ["payments", "critical", "prod"],
  "metadata_after": {
    "service_type": "payment gateway",
    "pci_scope": true,
    "ai_enrichment": {
      "environment": "prod",
      "category": "web",
      "criticality": "critical",
      "confidence": 0.9,
      "reasoning": "The subdomain 'payments.example.com' is classified as 'critical' due to its association with payment processing and PCI scope..."
    }
  }
}
```

---

### 4. Report generation — `POST /ai/report`

**Prompt:** Generate a security report filtered to services only

```bash
curl -X POST http://localhost:8000/ai/report \
  -H "Content-Type: application/json" \
  -d '{"filter": {"asset_type": "service"}}'
```

```json
{
  "report": {
    "title": "Security Report for Services",
    "executive_summary": "This report provides an overview of the security posture of 7 services in the dataset. The services are primarily active and associated with production, staging, and internal environments. However, some services have been identified as stale or potentially vulnerable.",
    "sections": [
      {
        "title": "Exposed Services",
        "content": "Services 4e43bb0d (443/tcp) and 6d64e02e (80/tcp) are exposed on the same IP address (203.0.113.10). Service 0ac2e897 (22/tcp) is also exposed on IP address 203.0.113.11.",
        "referenced_asset_ids": [
          "4e43bb0d-7d20-46a7-8c43-8e77fea8ffc5",
          "6d64e02e-a846-4b86-948e-b13ab3fc3611",
          "0ac2e897-53b7-41a4-ab49-02a709ca21ff"
        ]
      },
      {
        "title": "Stale Services",
        "content": "Service 46c33625 (21/tcp) is stale and may pose a security risk.",
        "referenced_asset_ids": ["46c33625-b603-4931-aa3d-313beefc79f1"]
      },
      {
        "title": "Internal Services",
        "content": "Service df7b3846 (5432/tcp) is an internal database service with IP address 10.0.0.5.",
        "referenced_asset_ids": ["df7b3846-35f0-4861-89de-aecac90a4d7a"]
      }
    ],
    "total_assets_analyzed": 7,
    "key_findings": [
      "Service 21/tcp is stale and may pose a security risk",
      "443/tcp and 80/tcp are co-exposed on IP 203.0.113.10",
      "5432/tcp (PostgreSQL) is an internal database service on 10.0.0.5"
    ],
    "overall_risk_level": "medium"
  },
  "grounding_validation": {
    "grounded": true,
    "hallucinated_ids": [],
    "flagged_sections": [],
    "total_assets_queried": 7,
    "asset_values_confirmed_in_text": ["443/tcp", "80/tcp", "22/tcp", "21/tcp", "5432/tcp"]
  }
}
```

> **Grounding note:** `hallucinated_ids: []` confirms the model referenced only the 7 assets it was given — zero hallucinations.




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
