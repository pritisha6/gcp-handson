# ETL Design Agent

An AI system that generates optimal Google Cloud Platform ETL/data-pipeline architectures
from a set of business and technical requirements — turning a ~15-20 minute conversation
with Claude into a reviewed, cost-estimated, compliance-checked design ready for
stakeholder sign-off.

You describe what you need (data sources, latency SLA, budget, team skills, compliance
requirements); the agent researches GCP service options, runs a Tree-of-Thought search to
pick the best ingestion → processing → storage → serving path, validates the result
against a battery of safety guardrails, and hands back an architecture diagram, cost
breakdown, compliance checklist, and implementation roadmap — plus a multi-stakeholder
approval workflow to sign off on it.

## How it works, end to end

```
 1. User uploads documents and/or fills out a requirements form (frontend)
          │
          ▼
 2. POST /api/designs/create → Design record saved (status=pending), generation
    kicked off as a background task
          │
          ▼
 3. ArchitectAgent runs a 16-cycle ReAct loop (LangGraph), grouped into 7 stages:
    Discovery → Conflict Detection → Service Selection (Tree-of-Thought) →
    Compliance → Cost Analysis → Validation (guardrails) → Documentation
          │
          ▼
 4. Design persisted to Firestore with output (diagram, decision matrix, cost
    analysis, compliance checklist, roadmap) + validation_results + metrics
          │
          ▼
 5. Stakeholders review the design and approve/request revisions (frontend)
          │
          ▼
 6. Everything is observable: structured logs, per-design + aggregate metrics,
    threshold alerts, and an immutable audit trail
```

### The core algorithm: Tree-of-Thought service selection

For each architecture layer (`ingestion → processing → storage → serving`), the agent:

1. **Generates candidates** (`ThoughtGenerator`) — asks Claude for 3-5 plausible GCP
   services for that layer, aware of what's already been picked upstream.
2. **Scores them** (`CriticEvaluator`) — each candidate gets a weighted score across
   latency (30%), cost (30%), ops burden (25%), and compliance (15%), using a mix of
   deterministic service-profile lookups and live RAG data (pricing, compliance rules).
3. **Prunes and selects** (`DecisionMaker`) — hard-fails candidates that miss the SLA or
   a compliance requirement outright, then keeps the top-`beam_width` survivors as a
   proper beam search (not greedy per-layer selection).
4. **Repeats** across all four layers, then returns the best complete path, with
   alternatives, once one of four conditions is met: depth limit reached, confidence
   threshold met, every branch pruned (escalate — no feasible architecture), or the time
   budget runs out.

### Safety guardrails

Before a design is considered done, `GuardrailValidator` runs ~17 checks across four
sets — input validation, service-selection feasibility, whole-design validation
(coverage, cost justification, compliance completeness, GCP quota realism, DR plan
presence), and behavioral checks (every choice explained, no unsourced factual claims,
overall confidence ≥ 0.7). Each check resolves to one of four actions:

| Status | Meaning |
|---|---|
| `PASS` | No issue, proceed. |
| `FLAG` | Issue noted, proceed anyway (e.g. a cost overage within 10%, negotiable). |
| `ESCALATE` | Pause for a human decision (e.g. a compliance gap, or >50% over budget → CFO sign-off). |
| `STOP` | Fatal — this candidate/design can't proceed as-is. |

A separate `HallucinationDetector` cross-checks every specific number/claim in the
design's reasoning text against the structured data that's actually traceable to a
retrieved document, API response, or cost calculation — flagging anything that isn't.

## Project structure

```
capstoneAgenticAI/
├── backend/            FastAPI + Pydantic + Firestore + Pinecone + Claude
│   ├── app/
│   │   ├── agents/      ThoughtGenerator, CriticEvaluator, DecisionMaker, StateManager
│   │   ├── services/    ArchitectAgent, ToT engine, RAG, guardrails, cost/compliance
│   │   │                 validators, document processing, metrics, logging, alerts
│   │   ├── routes/      /api/designs, /api/documents, /api/validate, /api/metrics
│   │   ├── db/          Firestore + Pinecone clients, collection schemas
│   │   ├── schemas/     Pydantic models (the API/domain contract)
│   │   └── utils/       config, logging, errors, caching, cost tracking
│   └── tests/unit/       pytest suite (96 tests)
└── frontend/           Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui
    └── src/
        ├── app/(routes)/  upload, design/[id], approval, history pages
        ├── components/    design visualizations, approval workflow, charts, ui primitives
        ├── lib/           typed API client, adapters, mermaid builder
        └── hooks/         data fetching, file upload, approval status (WS + polling)
```

## Tech stack

**Backend** — Python 3.11, FastAPI, Pydantic v2, LangGraph (agent orchestration),
Anthropic Claude (reasoning, extraction, hallucination checks), OpenAI embeddings +
Pinecone (RAG over uploaded documents), Google Cloud Firestore (storage), Google Cloud
Logging, GCP Billing Catalog API (live pricing, with a static fallback).

**Frontend** — Next.js 14 App Router, TypeScript (strict), Tailwind CSS, shadcn/ui
(Radix primitives), React Hook Form + Zod, Recharts, Mermaid, TanStack Table.

## Key API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/designs/create` | Submit requirements, kick off generation |
| `GET /api/designs/{id}` | Poll for the completed design |
| `GET /api/designs` | List/filter/paginate designs |
| `POST /api/documents/upload` | Upload & chunk source documents (PDF/PPTX/XLSX/HTML/TXT/CSV) into Pinecone |
| `POST /api/documents/extract` | Extract structured requirements from document text via Claude |
| `POST /api/validate/requirements` / `/design` | Run guardrails directly |
| `GET /api/metrics` | Aggregate quality/reliability/efficiency/user-impact metrics |
| `GET /api/metrics/trends` | Coverage/cost/generation-time trends |
| `GET /api/metrics/alerts` | Current threshold-crossing alerts |
| `GET /api/logs` | Query structured logs from Cloud Logging |

Full interactive docs are served at `/docs` when the backend is running.

## Running it locally

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env          # fill in CLAUDE_API_KEY, GCP_PROJECT_ID, PINECONE_API_KEY, OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

Run the test suite with `pytest tests/` (96 tests, all mocked — no live API keys needed).

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                        # http://localhost:3000
```

## What's real vs. approximate right now

This project is honest about the gap between "computed from real persisted data" and
"a reasonable placeholder until more data exists":

- **Metrics** (`/api/metrics`) are all derived from data the system actually stores
  (guardrail results, generation timing, API usage) — where a true signal doesn't exist
  yet (e.g. post-deployment cost accuracy, a real satisfaction survey), a documented
  proxy is used instead of a fabricated number. See `metrics_service.py` docstrings.
- **The approval workflow API** (`/api/designs/{id}/approval`) is not implemented on the
  backend yet — the frontend is built against the contract it should expose and degrades
  gracefully (empty state, not a crash) until it exists.
- **Real-time approval status** uses a WebSocket with automatic fallback to polling,
  since the backend doesn't expose that WebSocket yet either.
- **Datadog/Splunk log forwarding** and **Slack/email alerting** are fully implemented
  but inert until the relevant environment variables are set.

## License

Internal capstone project — no license specified.
