# Multi-Tenant Contract AI

FastAPI backend for tenant-isolated contract negotiation intelligence.

## Core Guarantees

- Tenant isolation at database level using PostgreSQL RLS (`app.tenant_id` session variable).
- Tenant isolation in vector search using per-tenant Qdrant collections (`<tenant>_contracts`).
- RBAC and API-key auth per tenant.
- Immutable audit log for auth and negotiation actions.

## Quick Start

1. Install dependencies.

```bash
cd D:/nego
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Create `.env`.

```bash
cat > .env <<'ENV'
NEGO_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/nego
NEGO_QDRANT_URL=http://localhost:6333

NEGO_AUTH_ENABLED=true
NEGO_AUTH_KEY_PEPPER=replace-with-strong-secret
NEGO_AUTH_BOOTSTRAP_TOKEN=replace-with-bootstrap-token

NEGO_CLAUSE_CLASSIFIER_PROVIDER=sklearn
NEGO_EMBEDDING_PROVIDER=sentence_transformers
NEGO_LLM_PROVIDER=openai_compatible
NEGO_LLM_API_BASE=https://your-llm-endpoint/v1
NEGO_LLM_API_KEY=replace-with-api-key
NEGO_LLM_MODEL=llama3
NEGO_CORPUS_ALLOWED_ROOTS=D:/nego
ENV
```

3. Apply database migrations.

```bash
alembic upgrade head
```

4. Run API.

```bash
uvicorn app.main:app --reload
```

## Alembic Workflow

- Config file: `alembic.ini`
- Env loader: `alembic/env.py`
- Initial revision: `alembic/versions/0001_initial_multi_tenant.py`

Common commands:

```bash
alembic current
alembic history
alembic revision --autogenerate -m "add new table"
alembic upgrade head
alembic downgrade -1
```

## Auth and RBAC Bootstrapping

You need a first tenant admin key before protected endpoints can be used.

1. Bootstrap tenant admin.

```bash
x`
```

2. Save returned `api_key` as `ADMIN_API_KEY`.

```bash
export TENANT_ID=tenant_acme
export ADMIN_API_KEY="PASTE_FROM_BOOTSTRAP_RESPONSE"
```

3. Verify actor context.

```bash
curl -X GET "http://127.0.0.1:8000/v1/auth/me" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${ADMIN_API_KEY}"
```

## User and Key Management

1. Create a legal reviewer.

```bash
curl -X POST "http://127.0.0.1:8000/v1/auth/users" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${ADMIN_API_KEY}" \
  -d '{
    "email": "reviewer@acme.com",
    "role": "legal_reviewer"
  }'
```

2. Create API key for that user.

```bash
curl -X POST "http://127.0.0.1:8000/v1/auth/keys" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${ADMIN_API_KEY}" \
  -d '{
    "user_id": "REPLACE_WITH_USER_ID",
    "scopes": []
  }'
```

3. Revoke a key prefix.

```bash
curl -X POST "http://127.0.0.1:8000/v1/auth/keys/revoke" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${ADMIN_API_KEY}" \
  -d '{
    "key_prefix": "abcdef123456"
  }'
```

## Core API Examples

Use an authorized key in `TENANT_API_KEY`.

```bash
export TENANT_API_KEY="PASTE_REVIEWER_OR_ADMIN_KEY"
```

1. Ingest a document.

```bash
curl -X POST "http://127.0.0.1:8000/v1/documents/ingest" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${TENANT_API_KEY}" \
  -d '{
    "client_id": "client_acme",
    "doc_type": "MSA",
    "counterparty_name": "Vendor A",
    "contract_value": 250000,
    "raw_text": "Limitation of Liability. Supplier liability is unlimited for all claims.\n\nConfidentiality. Each party will keep Confidential Information secret.",
    "metadata": {
      "source": "upload",
      "industry": "saas"
    }
  }'
```

2. Record negotiation outcome.

```bash
curl -X POST "http://127.0.0.1:8000/v1/outcomes" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${TENANT_API_KEY}" \
  -d '{
    "client_id": "client_acme",
    "doc_type": "MSA",
    "clause_type": "limitation_of_liability",
    "counterparty_name": "Vendor A",
    "deal_size": 250000,
    "original_text": "Supplier liability is unlimited.",
    "counterparty_edit": "Supplier liability is capped at 3x annual fees.",
    "client_response": "Cap must be 1x annual fees.",
    "final_text": "Supplier liability is capped at 1.5x annual fees.",
    "outcome": "partially_accepted",
    "negotiation_rounds": 3,
    "won_by": "mutual",
    "redline_events": [
      {
        "type": "deletion",
        "author": "counterparty",
        "timestamp": "2026-02-12T10:15:00Z"
      }
    ]
  }'
```

3. Generate strategic suggestion.

```bash
curl -X POST "http://127.0.0.1:8000/v1/strategy/suggest" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${TENANT_API_KEY}" \
  -d '{
    "analysis_scope": "single_client",
    "client_id": "client_acme",
    "doc_type": "MSA",
    "counterparty_name": "Vendor A",
    "contract_value": 350000,
    "new_clause_text": "Supplier liability is unlimited and includes consequential damages.",
    "top_k": 8
  }'
```

To analyze all clients inside a tenant, set:

```json
{
  "analysis_scope": "all_clients",
  "client_id": null
}
```

## Audit API

List tenant audit records.

```bash
curl -X GET "http://127.0.0.1:8000/v1/audit/logs?limit=50" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${ADMIN_API_KEY}"
```

## Corpus Learning API

This supports folder-based corpus learning per tenant (scan, learn, update, status),
including synthetic negotiation outcomes inferred from redlines and comments.
Each corpus source belongs to a `client_id` within that tenant.

Comment analysis tuning:

- `comment_rule_profile`: `strict`, `balanced`, or `lenient`
- `comment_accept_phrases` / `comment_reject_phrases` / `comment_revise_phrases`: per-tenant custom phrase lists

1. Scan folder and detect new/changed/learned files.

```bash
curl -X POST "http://127.0.0.1:8000/v1/corpus/scan" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${TENANT_API_KEY}" \
  -d '{
    "client_id": "client_acme",
    "source_path": "D:/nego/corpus/tenant_acme",
    "source_label": "Acme Corpus",
    "include_subdirectories": true,
    "max_files": 4000,
    "file_extensions": ["docx", "pdf", "txt", "md"]
  }'
```

2. Learn corpus (new and changed files by default).

```bash
curl -X POST "http://127.0.0.1:8000/v1/corpus/learn" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${TENANT_API_KEY}" \
  -d '{
    "client_id": "client_acme",
    "source_path": "D:/nego/corpus/tenant_acme",
    "source_label": "Acme Corpus",
    "include_subdirectories": true,
    "max_files": 4000,
    "file_extensions": ["docx", "pdf", "txt", "md"],
    "default_doc_type": "MSA",
    "counterparty_name": "Vendor A",
    "mode": "new_or_changed",
    "create_outcomes_from_redlines": false,
    "create_outcomes_from_comments": true,
    "comment_rule_profile": "balanced",
    "comment_accept_phrases": [],
    "comment_reject_phrases": [],
    "comment_revise_phrases": []
  }'
```

3. Update corpus incrementally.

```bash
curl -X POST "http://127.0.0.1:8000/v1/corpus/update" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${TENANT_API_KEY}" \
  -d '{
    "client_id": "client_acme",
    "source_path": "D:/nego/corpus/tenant_acme",
    "include_subdirectories": true,
    "max_files": 4000,
    "file_extensions": ["docx", "pdf", "txt", "md"],
    "default_doc_type": "MSA",
    "mode": "new_or_changed",
    "create_outcomes_from_redlines": false,
    "create_outcomes_from_comments": true,
    "comment_rule_profile": "balanced",
    "comment_accept_phrases": [],
    "comment_reject_phrases": [],
    "comment_revise_phrases": []
  }'
```

4. View current corpus status.

```bash
curl -X GET "http://127.0.0.1:8000/v1/corpus/status?client_id=client_acme&source_path=D:/nego/corpus/tenant_acme" \
  -H "X-Tenant-Id: ${TENANT_ID}" \
  -H "X-Api-Key: ${TENANT_API_KEY}"
```

## Provider Configuration

The strategy pipeline runs in LLM-only mode (draft -> verify -> consensus -> abstain).
Set these in `.env`:

- Clause classifier:

```bash
NEGO_CLAUSE_CLASSIFIER_PROVIDER=sklearn
NEGO_CLAUSE_CLASSIFIER_ARTIFACT_PATH=/abs/path/clause_classifier.joblib
```

- Embeddings:

```bash
NEGO_EMBEDDING_PROVIDER=sentence_transformers
NEGO_EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
```

- LLM suggestion engine:

```bash
NEGO_LLM_PROVIDER=openai_compatible
NEGO_LLM_API_BASE=https://your-llm-endpoint/v1
NEGO_LLM_API_KEY=replace-with-api-key
NEGO_LLM_MODEL=llama3
```

The API will fail fast at startup if `NEGO_LLM_PROVIDER` or `NEGO_LLM_API_BASE` are missing/invalid.

## Evaluation

Use labeled prediction logs to track accuracy and abstention:

```bash
python -m app.ml.evaluate_llm_pipeline --cases D:/nego/eval_cases.json
```

Each case should include:

- `expected_outcome`
- `expected_redline_contains` (optional list of required phrases)
- `actual_outcome`
- `actual_proposed_redline`
- `abstained` (true/false)

## Frontend

Ionic Angular frontend is available in `frontend`.

```bash
cd frontend
npm install
npm start
```

Notes:

- Angular CLI in this project requires Node `v20.19+` or `v22.12+`.
- Frontend coverage includes setup/health, auth/RBAC, contracts AI, corpus learning, and audit logs.



CREATE EXTENSION IF NOT EXISTS "uuid-ossp";



py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
 pip install -e .








   alembic upgrade head
   $env:NEGO_DATABASE_URL="postgresql+psycopg://postgres:1234@localhost:5432/nego"
  uvicorn app.main:app --reload

"# negitiation" 
