# PipeForge

PipeForge is an AI-assisted data product builder that turns natural-language business analytics requests into reviewable and executable data pipeline drafts.

It profiles available data sources, identifies business-critical decisions, generates dbt-style SQL/YAML/Markdown artifacts, and lets users test the generated SQL pipeline in a temporary demo data mart.

---

## Overview

PipeForge is designed for analytics, data engineering, and finance teams that need to quickly turn business requests into structured data product drafts.

A user can describe a business need such as:

```text
Our finance team needs a trusted monthly revenue dataset from Stripe for a board dashboard.
We need MRR by customer segment, but we are not sure how refunds and discounts should be handled.
Can you prepare this as a data product draft for our analytics team?
```

PipeForge then guides the request through a transparent workflow:

```text
Business request
→ request classification
→ source or data product selection
→ source profiling
→ business rule resolution
→ SQL/test/documentation artifact generation
→ executable demo pipeline
→ output table preview and CSV download
```

---

## Key Features

### Natural-Language Data Product Requests

Users describe the analytics output they need in plain English. PipeForge classifies the request and routes it to either:

- direct analytics question answering
- single-source data product generation
- multi-source/join-based data product generation

### Guided Agent Workflow

The backend runs a transparent workflow with multiple logical agents:

- Pipeline Architect
- Source Inspector
- Model Builder
- Test Writer
- Documentation Writer

The frontend displays run status, workflow trace, tool activity, generated artifacts, and execution results.

### Source Profiling

PipeForge inspects selected source tables and generates source context such as:

- row counts
- column names and types
- sample records
- contract-aware quality checks
- business-relevant data issues

Generated profiling artifacts include:

```text
source_profile.md
data_quality_report.md
relationship_profile.md
join_quality_report.md
join_plan.md
```

The multi-source artifacts are generated only when the selected data product requires joins.

### Business Rule Questions

When business logic is ambiguous, PipeForge pauses the workflow and asks the user for a decision.

Examples:

- how to handle refunds
- how to handle discounts
- how to treat unmatched invoices or payments
- whether to preserve currency or aggregate by currency
- how to handle duplicate business keys

The answers are stored as structured business rules and used during SQL generation.

### dbt-Style Artifact Generation

PipeForge generates reviewable artifacts such as:

```text
business_rules.yml
business_rules.md
stg_*.sql
int_*.sql
mart_*.sql
schema.yml
custom_tests/*.sql
pipeline_summary.md
```

The SQL follows a dbt-style model layering convention:

```text
staging model
→ intermediate model
→ final mart model
```

### Executable Demo Pipeline

After artifacts are generated, users can open the Pipeline tab and execute the generated SQL into a temporary SQLite demo mart.

The Pipeline tab supports:

- visual SQL lineage
- SQL model nodes
- dependency lines
- Run Pipeline / Run Again
- per-node SQL preview
- per-node table preview
- per-node CSV download
- ZIP download for all materialized tables

The demo mart is reset for each pipeline execution.

### Database Map

The Database tab visualizes the current demo database schema.

It displays:

- source tables
- table roles
- primary/foreign key information
- available metrics and dimensions
- configured relationships
- table details and column metadata

---

## Tech Stack

### Frontend

- React
- TypeScript
- Vite
- CSS

### Backend

- Python
- FastAPI
- SQLite
- Pydantic-style data structures
- OpenHands/LLM-based artifact generation

### Data Layer

- SQLite demo database
- Source contracts
- Semantic metadata
- Data product contracts
- dbt-style generated SQL

---

## Architecture

```text
User
  ↓
React Frontend
  ↓
FastAPI Backend
  ↓
Workflow Runner
  ↓
Metadata / Source / Data Product Selectors
  ↓
Source Profiling and Quality Checks
  ↓
Business Rule Resolution
  ↓
OpenHands / LLM Artifact Generation
  ↓
Artifact Store
  ↓
Pipeline Executor
  ↓
Temporary SQLite Demo Mart
```

---

## Main User Flow

1. The user enters a business analytics request in the Workflow tab.
2. The backend starts a PipeForge run.
3. The Pipeline Architect classifies the request.
4. PipeForge selects either a source table or a multi-source data product.
5. The selected source data is profiled.
6. PipeForge asks business rule questions when required.
7. The Model Builder generates SQL models.
8. The Test Writer generates schema and custom test artifacts.
9. The Documentation Writer generates documentation artifacts.
10. The Artifacts tab displays generated files.
11. The user opens the Pipeline tab.
12. The user runs the generated SQL pipeline.
13. PipeForge materializes output tables into a temporary demo mart.
14. The user previews or downloads the generated tables.

---

## Current Demo Domain

PipeForge currently uses a SaaS/Stripe-style demo finance domain.

Typical supported entities include:

```text
customers
plans
subscriptions
invoices
payments
```

Typical analytics requests include:

```text
MRR by customer segment
monthly revenue by currency
billing reconciliation
invoice/payment matching
collection health
outstanding invoice amount
revenue 360
```

---

## Backend Structure

```text
backend/app/
  api/
    routes_artifacts.py
    routes_database.py
    routes_health.py
    routes_pipeline.py
    routes_runs.py

  core/
    config.py
    paths.py

  contracts/
    sources/
    semantic/
    data_products/

  data/
    seed_demo_db.py

  prompts/
    model_builder_prompt.txt
    test_writer_prompt.txt
    documentation_writer_prompt.txt

  schemas/
    agents.py
    run.py

  services/
    analytics/
      analytics_query_runner.py
      direct_answer_formatter.py
      direct_query_classifier.py
      semantic_query_parser.py
      sql_query_planner.py
      sql_safety_validator.py

    artifacts/
      artifact_store.py

    database/
      database_service.py
      multi_source_profiler.py
      quality_checker.py
      schema_inspector.py
      source_profiler.py

    decisions/
      answer_queue.py
      answer_validator.py
      business_rule_resolver.py
      question_planner.py

    llm/
      llm_client.py
      llm_intent_classifier.py
      openhands_artifact_generator.py
      openhands_runner.py

    metadata/
      contract_loader.py
      data_product_selector.py
      database_graph_builder.py
      domain_relevance_classifier.py
      join_planner.py
      relationship_validator.py
      request_classifier.py
      semantic_layer_loader.py
      semantic_metadata_loader.py
      source_selector.py

    pipeline/
      dbt_sql_compiler.py
      pipeline_executor.py
      pipeline_sql_safety_validator.py

    runtime/
      event_emitter.py
      event_store.py
      run_registry.py

    workflows/
      pipeforge_workflow_runner.py

  utils/
    time.py

  main.py
```

---

## Frontend Structure

```text
frontend/src/
  api/
    pipelineApi.ts
    runsApi.ts

  components/
    artifacts/
      ArtifactCard.tsx
      ArtifactPanel.tsx

    chat/
      AskUserCard.tsx
      ChatPanel.tsx

    database/
      DatabaseMapPanel.tsx

    pipeline/
      PipelinePanel.tsx

    status/
      ActivityTicker.tsx
      ConnectionBadge.tsx
      ErrorPanel.tsx

    trace/
      TraceTreePanel.tsx

  hooks/
    useRunController.ts

  state/

  types/
    artifact.ts
    pipeline.ts
    run.ts

  App.tsx
  App.css
  main.tsx
```

---

## Important Backend Modules

### Workflow Runner

```text
backend/app/services/workflows/pipeforge_workflow_runner.py
```

Controls the end-to-end PipeForge workflow.

Responsibilities:

- start a run
- classify the request
- route to direct analytics, single-source generation, or multi-source generation
- call source profilers
- manage business rule questions
- call artifact generators
- emit workflow events
- mark run status

### Source Profiling

```text
backend/app/services/database/source_profiler.py
backend/app/services/database/multi_source_profiler.py
backend/app/services/database/quality_checker.py
backend/app/services/database/schema_inspector.py
```

Responsible for reading the demo database, inspecting selected tables, and producing source/data quality context.

### Metadata and Routing

```text
backend/app/services/metadata/domain_relevance_classifier.py
backend/app/services/metadata/request_classifier.py
backend/app/services/metadata/source_selector.py
backend/app/services/metadata/data_product_selector.py
backend/app/services/metadata/semantic_metadata_loader.py
backend/app/services/metadata/semantic_layer_loader.py
```

Responsible for determining whether a user request is relevant, what type of workflow should run, and which source/data product should be selected.

### Business Rules

```text
backend/app/services/decisions/question_planner.py
backend/app/services/decisions/answer_validator.py
backend/app/services/decisions/business_rule_resolver.py
backend/app/services/decisions/answer_queue.py
```

Responsible for identifying ambiguous business rules, asking questions, validating answers, and turning decisions into structured artifacts.

### Artifact Generation

```text
backend/app/services/llm/openhands_artifact_generator.py
backend/app/services/llm/openhands_runner.py
```

Responsible for generating SQL, YAML, and Markdown artifacts using the provided context and prompt templates.

### Artifact Storage

```text
backend/app/services/artifacts/artifact_store.py
```

Stores generated artifacts and makes them available to the frontend.

### Pipeline Execution

```text
backend/app/services/pipeline/dbt_sql_compiler.py
backend/app/services/pipeline/pipeline_executor.py
backend/app/services/pipeline/pipeline_sql_safety_validator.py
```

Responsible for compiling generated dbt-style SQL to SQLite-compatible SQL, validating SQL safety, and materializing generated models into a temporary demo mart.

### Runtime State

```text
backend/app/services/runtime/run_registry.py
backend/app/services/runtime/event_store.py
backend/app/services/runtime/event_emitter.py
```

Responsible for storing run state, events, and real-time workflow updates.

---

## Important Frontend Modules

### App Shell

```text
frontend/src/App.tsx
```

Top-level UI shell.

Responsibilities:

- top navigation
- workspace routing
- active page/tab state
- reset/new run behavior
- passing run state into panels

### Run Controller

```text
frontend/src/hooks/useRunController.ts
```

Responsible for starting runs, handling events, updating frontend run state, and submitting business rule answers.

### Artifact Panel

```text
frontend/src/components/artifacts/ArtifactPanel.tsx
```

Displays generated artifacts.

Features:

- search
- type filter
- artifact preview
- copy full content
- Test Pipeline button

### Pipeline Panel

```text
frontend/src/components/pipeline/PipelinePanel.tsx
```

Visual SQL pipeline execution page.

Features:

- SQL node graph
- dependency edges
- zoom and pan
- run pipeline button
- SQL preview
- table preview
- CSV download

### Database Map

```text
frontend/src/components/database/DatabaseMapPanel.tsx
```

Displays the database schema and relationships as an interactive visual map.

---

## Generated Artifacts

A typical single-source run may generate:

```text
source_profile.md
data_quality_report.md
business_rules.yml
business_rules.md
stg_stripe__payments.sql
int_payments__revenue_rules.sql
mart_revenue__monthly_by_segment.sql
schema.yml
custom_tests/test_mrr_not_null.sql
pipeline_summary.md
```

A typical multi-source run may additionally generate:

```text
relationship_profile.md
join_quality_report.md
join_plan.md
```

---

## Pipeline Execution Model

The Pipeline tab executes generated SQL artifacts in dependency order.

The executor:

1. collects generated model SQL files
2. excludes custom tests and direct analytics SQL
3. extracts `ref()` dependencies
4. sorts models by dependency
5. resets the run-specific demo mart
6. attaches the source SQLite database
7. compiles dbt-style SQL to SQLite SQL
8. validates SQL safety
9. creates one table per generated model
10. exposes table previews and CSV downloads

Example model order:

```text
stg_stripe__payments
→ int_payments__revenue_rules
→ mart_revenue__monthly_by_segment
```

---

## SQL Generation Rules

Generated model SQL should follow these rules:

- use only available source tables
- use `{{ source(...) }}` for raw source tables
- use `{{ ref(...) }}` for generated model dependencies
- use SQLite-compatible SQL
- produce one SELECT/WITH statement per model
- avoid DDL/DML statements
- avoid unsupported warehouse-specific syntax
- do not invent external lookup tables
- preserve currency grouping unless a currency conversion source exists

---

## Running the Project

From the project root:

```bash
docker compose up
```

Rebuild backend:

```bash
docker compose build --no-cache backend
```

Rebuild frontend:

```bash
docker compose build --no-cache frontend
```

Rebuild both services:

```bash
docker compose down
docker compose build --no-cache backend frontend
docker compose up
```

The frontend is usually available at:

```text
http://localhost:5173
```

The backend is usually available at:

```text
http://localhost:8000
```

---

## Seeding the Demo Database

If the database needs to be reset or reseeded:

```bash
docker compose exec -T backend python -m app.data.seed_demo_db
```

---

## Basic Usage

1. Start the app with Docker Compose.
2. Open the frontend in the browser.
3. Enter a business analytics request.
4. Resolve any business rule questions.
5. Review generated artifacts.
6. Click **Test pipeline** from the Artifacts tab or open the Pipeline tab.
7. Click **Run pipeline**.
8. Preview generated output tables.
9. Download CSV outputs if needed.

---

## Example Prompts

### Single-source revenue dataset

```text
Create a trusted monthly revenue dataset from Stripe payments.
We need MRR by customer segment and currency.
We are not sure how refunds and discounts should be handled.
Prepare this as a data product draft for the analytics team.
```

### Invoice amount quality summary

```text
Create a dbt-style data product from stripe_invoices only.
I want an invoice amount quality summary that calculates minimum invoice amount,
maximum invoice amount, average invoice amount, invoice count, and total billed amount by currency.
Generate reviewable SQL models and documentation.
```

### Billing reconciliation

```text
Create a dbt-style billing reconciliation data product that joins stripe_invoices and stripe_payments by invoice_id.
Compare billed invoice revenue with collected payment revenue, identify invoices without matching payments,
identify partial payments and overpayments, and produce a monthly reconciliation mart by customer_segment and currency.
```

### Revenue 360

```text
Create a revenue 360 data product that combines customers, subscriptions, plans, invoices, and payments.
Build a monthly mart with billed revenue, collected revenue, MRR, customer segment, country, industry,
plan name, product family, and currency.
```

---

## API Areas

Main backend API areas include:

```text
/api/runs
/api/artifacts
/api/database
/api/pipeline
/api/health
```

The exact route implementations are located in:

```text
backend/app/api/
```

---

## Development Notes

The backend service paths are centralized through:

```text
backend/app/core/paths.py
```

Use this module for app-level paths such as:

```text
contracts
semantic contracts
prompts
```

Avoid calculating app root paths manually inside service files.

---

## Project Status

PipeForge is currently a local demo/prototype for transparent AI-assisted data product generation and execution.

Current strengths:

- business request to artifact generation
- source profiling
- business-rule clarification
- SQL/test/docs generation
- visual database map
- visual executable pipeline
- temporary demo mart execution

Current limitations:

- SQLite demo execution is not a full dbt runtime
- generated SQL is constrained to SQLite-compatible syntax
- production warehouse integrations are not included
- long-running workflow persistence is limited to current demo state
- multi-user execution isolation is not production-grade

---

## Author

Developed by **Tuan Ta Anh**

GitHub:

https://github.com/tuanTaAnh