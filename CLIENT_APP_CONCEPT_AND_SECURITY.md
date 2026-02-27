# AI Contract Negotiation Platform
## Client Concept and Security Brief

## 1) Executive Summary

This platform helps legal and procurement teams negotiate contracts faster, with better consistency and lower risk. It combines clause intelligence, historical negotiation learning, and strategic AI recommendations inside a strict multi-tenant security model.

The platform is designed for legal SaaS environments where data separation, auditability, and predictable controls are mandatory.

## 2) Business Problem It Solves

Contract teams typically face four issues:

- Negotiation cycles are slow and repetitive.
- Knowledge is fragmented across people, email threads, and redlines.
- Risk decisions are inconsistent across deals.
- There is limited visibility into why clauses are accepted or rejected.

This platform converts negotiation history into a reusable legal intelligence system.

## 3) Product Concept

The product has four intelligence layers:

1. Clause Intelligence
- Parses uploaded contracts.
- Segments documents into clauses.
- Classifies clause type (for example: limitation of liability, indemnity, confidentiality).
- Generates embeddings for semantic retrieval.

2. Negotiation Outcome Learning
- Stores original language, edits, counter-edits, outcomes, negotiation rounds, and winner.
- Learns tenant-specific negotiation behavior over time.

3. Smart Retrieval
- Retrieves similar prior clauses using tenant-safe vector search.
- Re-ranks results with business context (counterparty, outcome, value similarity, confidence).

4. Strategic Suggestion Engine
- Produces recommended redline language.
- Explains business rationale.
- Suggests fallback positions.
- Predicts acceptance probability and risk score.

## 4) End-to-End Workflow

1. User uploads a contract.
2. Document is segmented into clauses.
3. Clause types are identified and indexed.
4. Embeddings are written to tenant-specific vector collection.
5. User submits or imports negotiation outcomes.
6. System updates tenant profiles and retrieval signals.
7. On new clause review, system returns:
- Suggested redline
- Risk estimate
- Acceptance probability
- Fallback position
- Relevant historical examples

## 5) Multi-Tenant Isolation Model

Tenant isolation is enforced across storage, retrieval, and application context.

### Database Isolation

- Every business table includes `tenant_id`.
- Contract intelligence tables also include `client_id` for sub-segmentation within each tenant.
- PostgreSQL Row-Level Security (RLS) is enabled and forced.
- Per request, app sets `app.tenant_id` session context.
- Policies allow read/write only where `tenant_id = current_setting('app.tenant_id')`.

### Vector Isolation

- Vector database: Qdrant.
- Collection naming pattern: `<tenant>_contracts`.
- No shared cross-tenant vector collection.

### Prompt and Retrieval Isolation

- Retrieval is filtered by tenant and clause criteria.
- Retrieval scope can be either one `client_id` or all clients inside the same tenant.
- Strategy engine consumes only tenant-scoped examples.
- No cross-tenant context mixing in prompts.

## 6) Security Architecture

### 6.1 Identity and Access Control

- API-key authentication (per tenant).
- Role-based access control (RBAC).
- Roles include:
- `admin`
- `legal_reviewer`
- `analyst`
- `viewer`
- Scope-aware permission checks for each endpoint.
- Bootstrap token flow only for first tenant admin initialization.

### 6.2 Data Protection

- Tenant-level separation via RLS.
- Hashed API credentials (no plain-text key storage).
- Security metadata and actions captured in audit log.
- Structured redline events retained for traceability.

### 6.3 Audit and Forensics

Audit log records:

- Actor
- Action
- Resource type and ID
- Request ID
- IP address
- Timestamp
- Metadata payload

This supports internal audit, incident investigations, and client assurance reviews.

### 6.4 Application Security Controls

- Permission checks before business logic execution.
- Endpoint-specific authorization gates.
- Tenant context required via header.
- Predictable failure behavior with controlled error handling.

### 6.5 AI Safety Controls

- Tenant-only retrieval context for AI suggestions.
- Fallback deterministic behavior if external model integration fails.
- Model provider abstraction allows controlled model governance.

## 7) Compliance and Governance Alignment

The architecture is designed to support:

- SOC 2 control mapping
- ISO 27001 control mapping
- Vendor security due diligence questionnaires
- Legal and procurement audit evidence collection

Recommended governance artifacts for enterprise rollout:

- Data classification and retention policy
- Access review and key rotation policy
- Incident response runbook
- Model change management policy
- Subprocessor and data residency declaration

## 8) Current Implementation Status

Implemented in current application:

- FastAPI API layer
- PostgreSQL schema with tenant RLS
- Qdrant tenant collections
- Clause segmentation/classification/embedding pipeline
- Outcome storage and retrieval scoring
- Corpus outcome synthesis from redlines and comments (with strict/balanced/lenient rule profiles)
- Strategy suggestion service (rule-based + LLM adapter)
- RBAC, API keys, bootstrap admin flow
- Tenant audit log endpoints
- Alembic migration scaffolding

Configurable model providers currently supported:

- Clause classifier: keyword or sklearn artifact
- Embeddings: deterministic or sentence-transformers
- Acceptance model: baseline, sklearn, xgboost artifact
- LLM engine: rule-based or OpenAI-compatible endpoint (including local Ollama via compatibility API)

## 9) Frontend Experience and Controls

The application includes an Ionic Angular frontend for operations teams:

- Setup and Health page for API base URL, tenant ID, API key, and bootstrap token.
- Auth and RBAC page for admin bootstrap, user creation, key creation, and key revocation.
- Contracts AI page for document ingestion, outcome recording, and strategy suggestions.
- Corpus Learning page for folder scan, learn, incremental update, and corpus status.
- Audit Logs page for tenant action review and traceability.

Frontend security model:

- Tenant header and API key are required for protected API calls.
- No cross-tenant data joins are possible because backend RLS policies enforce tenant context.
- All high-risk actions are written to audit logs with request identifiers.

## 10) Deployment Options

### Option A: Central SaaS (Shared Infrastructure)

Best for rapid rollout and lower cost.

- Shared control plane
- Tenant-isolated data plane
- Standardized upgrade cycle

### Option B: Dedicated Tenant Deployment

Best for highly regulated environments.

- Isolated runtime per tenant
- Stronger network and residency controls
- Higher operational cost

## 11) Client Value

The platform delivers measurable value in three areas:

1. Speed
- Faster clause review and negotiation turnaround.

2. Quality
- Consistent legal positions and fallback logic.

3. Risk Control
- Better predictability of negotiation outcomes with evidence-based recommendations.

## 12) Recommended Next Steps

1. Confirm target deployment model (central SaaS vs dedicated).
2. Finalize model stack for production (local LLM vs managed endpoint).
3. Define compliance package scope (SOC 2 only vs SOC 2 + ISO 27001).
4. Start pilot with one legal team and 2-3 high-volume contract types.
