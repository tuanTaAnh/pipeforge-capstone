# PipeForge

**Live demo:** https://anhtuan19981998-pipeforge-demo.hf.space

PipeForge is an LLM-powered data pipeline builder that turns natural-language analytics requests into transparent data workflows, SQL artifacts, data product drafts, tests, documentation, and executable pipeline outputs.

The project demonstrates how an AI system can combine metadata-aware planning, human-in-the-loop clarification, source profiling, SQL generation, validation, targeted repair, and a traceable frontend experience for analytics engineering workflows.

---

## Overview

PipeForge accepts a business analytics request such as:

```text
Our finance team needs a trusted monthly revenue dataset from Stripe for a board dashboard. We need MRR by customer segment, but we are not sure how refunds and discounts should be handled. Can you prepare this as a data product draft for our analytics team?
```

The system then:

1. Loads source metadata, semantic definitions, relationships, and data product contracts.
2. Uses an LLM request planner to classify the request.
3. Routes the request to either direct analytics or data product generation.
4. Asks the user for clarification when a business rule is ambiguous.
5. Profiles selected sources with code/tools.
6. Generates SQL models, tests, and documentation using bounded agent tasks.
7. Validates generated artifacts with deterministic code.
8. Repairs only failed artifacts when needed.
9. Streams every step to the frontend as a real-time execution trace.

The goal is not only to generate outputs, but to make the reasoning, tool calls, artifacts, validation, and final results visible and reviewable.

---

## Key Features

### 1. Natural-language request planning

PipeForge uses an LLM planner to understand whether a request is:

- A direct analytics question
- A data product / pipeline generation request
- A request that needs user clarification
- An out-of-scope question

Example direct analytics request:

```text
Who is the customer with highest MRR?
```

Example data product request:

```text
Create a monthly billed revenue pipeline from Stripe invoices for the analytics team.
```

---

### 2. Direct analytics mode

For simple analytical questions, PipeForge generates a safe read-only SQL query, validates it, executes it, and returns answer artifacts.

Typical output artifacts:

```text
semantic_query_plan.json
analytics_query.sql
analytics_result.json
analytics_answer.md
```

Example:

```text
What are the minimum and maximum successful payment amounts?
```

Expected behavior:

- Selects the relevant source table
- Generates safe SQL
- Executes the query
- Returns a concise answer and result artifact

---

### 3. Data product generation mode

For broader requests such as building a reusable dataset, mart, or pipeline, PipeForge generates dbt-style artifacts.

Typical generated artifacts include:

```text
source_profile.md
data_quality_report.md
relationship_profile.md
join_quality_report.md
artifact_plan.json
business_rules.yml
business_rules.md
stg_*.sql
int_*.sql
mart_*.sql
schema.yml
custom_tests/*.sql
pipeline_summary.md
```

The generated pipeline can then be reviewed and executed from the frontend.

---

### 4. Human-in-the-loop business clarification

When the user request contains ambiguous business logic, PipeForge asks a structured clarification question instead of guessing.

Example:

```text
We need MRR by customer segment, but we are not sure how refunds and discounts should be handled.
```

PipeForge may ask:

```text
How should refunds and discounts be handled in the monthly revenue data product?
```

Example options:

```text
Report gross MRR only and show adjustments separately
Report net MRR after discounts and refunds
Report both gross MRR and net MRR with adjustment breakdown
```

The selected answer is stored as a business rule and used by downstream generation.

---

### 5. Metadata-grounded generation

PipeForge does not rely only on natural language prompts. It uses metadata contracts to constrain the system.

The backend loads:

```text
Source contracts
Column definitions
Semantic metrics
Semantic dimensions
Relationships
Data product contracts
Known limitations
```

This allows the LLM and agents to work within known schema boundaries instead of inventing unavailable tables or columns.

---

### 6. Source profiling and validation

Before generating artifacts, PipeForge profiles selected tables using code/tools.

Profiling may include:

```text
row counts
null rates
duplicate keys
distinct values
date/month ranges
sample values
relationship validity
join quality
```

Generated artifacts are then validated by code for:

```text
expected files
safe SQL
valid YAML
allowed source references
allowed model references
known source/column usage
month-key handling
```

---

### 7. Bounded OpenHands-based artifact generation

PipeForge uses bounded agent-style tasks for generation.

Specialized generation tasks include:

```text
model-builder
test-writer
doc-writer
```

Each task receives:

```text
expected files
allowed sources
artifact plan
source profile
business rules
validation context
```

The system avoids unrestricted agent loops by using clear task scopes, expected outputs, validation, and targeted repair.

---

### 8. Real-time frontend trace

The frontend shows the workflow as it happens.

Main UI areas:

```text
Request console
Execution trace
Artifact viewer
Database map
Pipeline execution panel
Logs
```

The backend streams normalized events such as:

```text
session_started
agent_started
tool_started
ask_user
ask_user_answered
artifact_created
agent_completed
final_message
done
```

This makes the full pipeline transparent and reviewable.

---

## Demo Data Model

PipeForge currently uses a simplified Stripe-style demo database.

### `dim_customers`

```text
customer_id
customer_name
customer_segment
```

### `dim_plans`

```text
plan_id
plan_name
```

### `fact_subscriptions`

```text
subscription_id
customer_id
plan_id
mrr_amount
```

### `stripe_invoices`

```text
invoice_id
subscription_id
invoice_month
invoice_amount
discount_amount
```

### `stripe_payments`

```text
payment_id
invoice_id
payment_month
successful_amount
refund_amount
```

The database is intentionally compact so the demo can focus on metadata-driven planning, LLM orchestration, pipeline generation, validation, and reviewability.

---

## Example Prompts

### Out-of-scope request

```text
Who won the football match yesterday?
```

Expected behavior:

```text
Returns out-of-scope response.
Does not generate SQL.
Does not generate pipeline artifacts.
```

---

### Direct analytics request

```text
Who is the customer with highest MRR?
```

Expected behavior:

```text
Generates and executes SQL using fact_subscriptions and dim_customers.
Returns the top customer by total MRR.
```

---

### Ambiguous analytics request

```text
Show me revenue for May 2026.
```

Expected behavior:

```text
Asks which revenue definition should be used:
billed revenue, collected revenue, gross MRR, or net MRR.
```

---

### Simple pipeline request

```text
Create a monthly billed revenue pipeline from Stripe invoices for the analytics team.
```

Expected behavior:

```text
Generates a pipeline/data product draft using invoice data.
Creates SQL models, tests, and documentation.
```

---

### Human-in-the-loop data product request

```text
Our finance team needs a trusted monthly revenue dataset from Stripe for a board dashboard. We need MRR by customer segment, but we are not sure how refunds and discounts should be handled. Can you prepare this as a data product draft for our analytics team?
```

Expected behavior:

```text
Asks how refunds and discounts should be handled.
Uses the user answer to generate business rules.
Builds a monthly revenue data product draft.
Generates staging, intermediate, mart, test, and documentation artifacts.
```

---

## Architecture

PipeForge is built as a full-stack application.

```text
Frontend: React + Vite + TypeScript
Backend: FastAPI + Python
Database: SQLite demo database
LLM layer: LiteLLM-compatible client
Agent execution: OpenHands-based bounded artifact generation
Deployment: Docker / Hugging Face Spaces
```

High-level runtime architecture:

```text
User request
   |
   v
FastAPI backend
   |
   v
Metadata context builder
   |
   v
LLM request planner
   |
   +-------------------------+
   |                         |
   v                         v
Direct analytics         Data product generation
   |                         |
   v                         v
SQL planner              Source inspector
   |                         |
   v                         v
SQL validator            Business decision planner
   |                         |
   v                         v
SQL execution            Artifact planner
   |                         |
   v                         v
Answer artifacts         Model/Test/Doc agents
                             |
                             v
                         Artifact validation
                             |
                             v
                         Targeted repair if needed
                             |
                             v
                         Final artifacts
```

---

## Backend Flow

### Step 1 — Load metadata context

The backend reads YAML contracts, semantic metadata, schema definitions, relationships, metrics, dimensions, data products, and known limitations.

### Step 2 — LLM Request Planner

The request planner receives the user question, metadata context, and previous user answers. It returns a structured JSON plan including:

```text
request_type
selected_sources
selected_metrics
selected_dimensions
selected_data_product
clarification_required
business_interpretation
assumptions
warnings
```

### Step 3 — Code validation

The backend validates the planner output against known metadata.

It rejects unknown sources, metrics, dimensions, or data products.

### Step 4 — Ask user if needed

If the planner marks a business decision as required, the backend streams an `ask_user` event to the frontend.

### Branch A — Direct Analytics

For direct analytics requests, the backend:

```text
generates SQL
validates SQL safety
executes SQL
returns analytics artifacts
```

### Branch B — Data Product Generation

For data product requests, the backend:

```text
loads selected contracts
profiles real data
asks for business decisions if needed
creates artifact_plan.json
dispatches model/test/doc generation tasks
validates generated artifacts
repairs failed artifacts only
returns final artifacts
```

### Cross-cutting behavior

Every major step emits structured events to the frontend so the user can inspect the workflow in real time.

---

## Folder Structure

A simplified overview of the main project structure:

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes_answers.py
│   │   │   ├── routes_artifacts.py
│   │   │   ├── routes_database.py
│   │   │   ├── routes_health.py
│   │   │   ├── routes_pipeline.py
│   │   │   └── routes_runs.py
│   │   ├── contracts/
│   │   │   ├── catalog.yml
│   │   │   ├── dim_customers.yml
│   │   │   ├── dim_plans.yml
│   │   │   ├── fact_subscriptions.yml
│   │   │   ├── stripe_invoices.yml
│   │   │   ├── stripe_payments.yml
│   │   │   ├── relationships.yml
│   │   │   ├── data_products/
│   │   │   └── semantic/
│   │   ├── core/
│   │   ├── prompts/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── analytics/
│   │   │   ├── artifacts/
│   │   │   ├── database/
│   │   │   ├── decisions/
│   │   │   ├── llm/
│   │   │   ├── metadata/
│   │   │   ├── pipeline/
│   │   │   ├── planning/
│   │   │   ├── runtime/
│   │   │   ├── validation/
│   │   │   └── workflows/
│   │   ├── utils/
│   │   └── main.py
│   ├── data/
│   │   └── pipeforge_demo.db
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── state/
│   │   ├── types/
│   │   ├── App.tsx
│   │   └── main.tsx
│   └── package.json
│
├── Dockerfile
├── docker-compose.yml
├── README.md
└── .dockerignore
```

---

## Important Backend Modules

### `backend/app/services/workflows/pipeforge_workflow_runner.py`

Main workflow orchestrator.

It controls the end-to-end run lifecycle, including request planning, direct analytics, data product generation, profiling, artifact generation, validation, and final response.

### `backend/app/services/planning/`

Contains LLM and deterministic planning components:

```text
llm_request_planner.py
llm_direct_query_planner.py
llm_business_decision_planner.py
llm_artifact_planner.py
request_plan_validator.py
direct_query_validator.py
artifact_plan_validator.py
planner_repair.py
metadata_context_builder.py
data_product_plan_builder.py
```

### `backend/app/services/database/`

Contains schema inspection, source profiling, data quality checks, and multi-source profiling logic.

### `backend/app/services/llm/`

Contains the LLM client and OpenHands-based artifact generation logic.

### `backend/app/services/artifacts/`

Stores and validates generated artifacts.

### `backend/app/services/pipeline/`

Compiles and executes generated SQL pipeline artifacts.

### `backend/app/services/runtime/`

Handles event streaming, event storage, run registry, and flow logging.

---

## Important Frontend Modules

### `frontend/src/App.tsx`

Main application shell and page navigation.

### `frontend/src/api/`

Frontend API clients for:

```text
runs
answers
artifacts
database graph
pipeline execution
event stream
```

### `frontend/src/hooks/useRunController.ts`

Controls run lifecycle state and user actions.

### `frontend/src/hooks/useEventStream.ts`

Connects to backend SSE events and streams agent workflow updates.

### `frontend/src/state/runReducer.ts`

Applies backend events to frontend run state.

### `frontend/src/components/`

Main UI components for:

```text
chat/request console
execution trace
artifact viewer
database map
pipeline panel
status and error panels
```

---

## Running Locally with Docker Compose

The easiest way to run the app locally is:

```bash
docker compose up --build
```

Then open:

```text
http://localhost:5173
```

Local development uses:

```text
Frontend: http://localhost:5173
Backend:  http://localhost:8000
```

---

## Running Locally with Single Docker Container

The repository also supports a production-style single-container build.

Build:

```bash
docker build -t pipeforge-hf .
```

Run:

```bash
docker run --rm -p 7860:7860 \
  -e APP_ENV=production \
  -e PORT=7860 \
  -e BACKEND_PORT=7860 \
  -e LLM_API_KEY="your_api_key_here" \
  -e LLM_MODEL="gpt-5.1-codex-mini" \
  -e LLM_BASE_URL="https://opencode.ai/zen/v1" \
  -e OPENHANDS_MAX_CONCURRENCY=1 \
  -e OPENHANDS_TASK_DELAY_SECONDS=0 \
  -e OPENHANDS_TIMEOUT_SECONDS=300 \
  -e OPENHANDS_REPAIR_ATTEMPTS=1 \
  -e OPENHANDS_WORKSPACE_DIR="/app/workspace" \
  -e OPENHANDS_SUPPRESS_BANNER=1 \
  -e DATABASE_URL="sqlite:////app/data/pipeforge_demo.db" \
  -e CORS_ORIGINS="*" \
  -e USE_LLM_QUESTION_PLANNER=1 \
  -e QUESTION_PLANNER_MAX_MUST_ANSWER=3 \
  pipeforge-hf
```

Then open:

```text
http://localhost:7860
```

---

## Environment Variables

Create local `.env` files for development, but do not commit real secrets.

Important backend variables:

```env
APP_ENV=development
BACKEND_PORT=8000

LLM_API_KEY=your_api_key_here
LLM_MODEL=gpt-5.1-codex-mini
LLM_BASE_URL=https://opencode.ai/zen/v1

OPENHANDS_MAX_CONCURRENCY=1
OPENHANDS_TASK_DELAY_SECONDS=0
OPENHANDS_TIMEOUT_SECONDS=300
OPENHANDS_REPAIR_ATTEMPTS=1
OPENHANDS_WORKSPACE_DIR=/app/workspace
OPENHANDS_SUPPRESS_BANNER=1

DATABASE_URL=sqlite:////app/data/pipeforge_demo.db

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

USE_LLM_QUESTION_PLANNER=1
QUESTION_PLANNER_MAX_MUST_ANSWER=3
```

For production-style single-container deployment, the frontend should use same-origin API paths.

In the current setup:

```text
API_BASE = ""
```

and frontend API calls use paths such as:

```text
/api/runs
/api/database/graph
/api/runs/{runId}/events
```

---

## Deployment Notes

The live demo is deployed as a Docker-based Hugging Face Space.

Deployment approach:

```text
Build React frontend into static files
Copy frontend build into backend image
Run FastAPI on port 7860
Serve both API routes and React frontend from one container
```

The backend serves:

```text
/api/...        backend API
/assets/...     frontend assets
/               React app
/{path}         React route fallback
```

---

## Validation and Safety

PipeForge includes deterministic validation layers to reduce hallucinated or unsafe outputs.

Validation includes:

```text
Planner output schema validation
Known source/metric/dimension validation
Read-only SQL validation
Allowed source/ref validation
Generated artifact file validation
YAML parsing
Month-key handling checks
Pipeline execution checks
```

The system is designed to reject or repair generated artifacts that reference unavailable sources, unavailable columns, unsafe SQL, or invalid model dependencies.

---

## Known Constraints

This is a compact demo system with a simplified SQLite database.

Current constraints:

```text
No currency conversion
No FX tables
No subscription status column
No payment status column
No external warehouse connection
No persistent production database
```

The simplified database is intentional so the focus remains on LLM planning, metadata grounding, human-in-the-loop decisions, artifact generation, and validation.

---

## Author

Developed by **Tuan Ta Anh**

GitHub:

https://github.com/tuanTaAnh