# void-server

> Monorepo for an AI Incident Monitoring and Analysis system. Detects, evaluates, fingerprints, and forms engineering-ready incidents from AI agent execution telemetry, then generates GitHub Issues with root cause analysis.

**Runtime:** TypeScript (Node.js, Express, BullMQ) + Python (FastAPI, Gemini, PydanticAI)
**Infrastructure:** PostgreSQL 16, Redis 7, Docker Compose

---

## Monorepo Structure

```text
void-server/
├── docker-compose.yml          # PostgreSQL 16, Redis 7, Adminer
├── turbo.json                  # Turborepo task runner
├── package.json                # npm workspaces root
│
├── apps/
│   ├── node-api/               # Express API (port 3001) + BullMQ worker
│   │   └── src/
│   │       ├── index.ts        # Express server: /health, /api/incidents
│   │       └── worker.ts       # BullMQ worker: spawns Python evaluator subprocess
│   │
│   └── fastapi-api/            # FastAPI service (port 8000), SQLAlchemy
│       ├── main.py             # /health, /api/incidents, /api/reports
│       ├── database.py         # SQLAlchemy session
│       └── models.py           # Incident & Report ORM models
│
├── packages/
│   ├── db/                     # Shared Prisma client + schema
│   │   └── prisma/schema.prisma   # Incident 1:N Report, JSONB fields
│   │
│   ├── risk-engine/            # Deterministic risk evaluation (TS)
│   │   └── src/
│   │       ├── evaluator.ts    # Orchestrator: 8 policy checks → labels
│   │       ├── types.ts        # RiskLabel enum (10 values)
│   │       └── policies/       # 8 policies (latency, tokens, crashes...)
│   │
│   ├── incident-fingerprint/   # SHA-256 dedup fingerprinting (TS)
│   │   └── src/
│   │       ├── risk-labels.ts  # normalizeRiskLabels() — dedup, sort, validate
│   │       └── incident-fingerprint.ts  # generateFingerprint()
│   │
│   ├── incident-formation/     # Persistence + BullMQ queue (TS)
│   │   └── src/
│   │       ├── service.ts      # Severity-routed orchestration
│   │       ├── repository.ts   # PrismaIncidentRepository
│   │       └── queue.ts        # BullMqIncidentQueue
│   │
│   ├── adaptive-sampling/      # 1-in-N sampling of healthy executions (TS)
│   │   └── src/
│   │       ├── service.ts      # Window-based random sampling
│   │       └── queue.ts        # BullMqSamplingQueue
│   │
│   ├── evaluator/              # AI incident evaluator (Python/Gemini)
│   │   └── src/evaluator/
│   │       ├── __main__.py     # CLI: stdin → JSON
│   │       ├── agent.py        # Orchestrator: context → prompt → Gemini → validate → score
│   │       ├── context_builder.py  # Parse incident → EvaluationContext
│   │       ├── prompt_builder.py   # Build Gemini prompt (v3)
│   │       ├── gemini_client.py    # Gemini API call (gemini-3.1-flash-lite)
│   │       ├── validator.py        # JSON parse + Pydantic validation
│   │       └── scorer.py           # Deterministic confidence adjustments
│   │
│   └── issue-agent/            # AI GitHub issue generator (Python/PydanticAI)
│       └── src/issue_agent/
│           ├── __main__.py     # CLI: stdin → EngineeringReport / GitHub Issue
│           ├── agent.py        # PydanticAI Agent with 4 tools
│           ├── evidence.py     # Extract failed tool calls from trace
│           ├── repository.py   # GitHubRepo (prod) / LocalRepo (dev)
│           └── schemas.py      # IncidentSnapshot, EngineeringReport (18 fields)
│
└── evaluation_dataset/         # 16 incident scenarios for testing
    └── incidents/
        ├── example/
        ├── context-overflow/
        ├── tool-anomaly/
        ├── looping/
        └── ... (16 total)
```

---

## Pipeline

```text
Agent Execution Telemetry
        │
        ▼
  POST /api/traces
  [apps/node-api]
        │
        ▼
  Risk Engine (8 policies)
  [packages/risk-engine]
        │
        ▼
  normalizeRiskLabels()
  [packages/incident-fingerprint]
        │
        ▼
  IncidentFormationService
  [packages/incident-formation]
        │
    ┌────┴─────────┐
    │              │
 HEALTHY      SUSPICIOUS
    │          / CRITICAL
    │              │
    ▼              ▼
 Adaptive      persist
 Sampling      + queue
 (1-in-N)     [incident-analysis]
    │              │
    ▼              ▼
 sampling-     worker.ts
 consumer.ts   evaluator
 (evaluator)   → promotion gate
    │          → issue agent
    │              │
    ▼              ▼
 promotion?   engineering report
    │          + GitHub issue
 ┌──┴──┐
 no   yes
 │     │
skip  IncidentFormationService
      (SUSPICIOUS)
      → incident-analysis queue
      → worker.ts (same as above)
```

---

## What We've Implemented

| Layer | Package | Status | Details |
|---|---|---|---|
| **Risk Detection** | `risk-engine` | ✅ Complete | 8 deterministic policies, severity assignment, 90+ tests |
| **Fingerprinting** | `incident-fingerprint` | ✅ Complete | SHA-256 dedup, label normalization |
| **Incident Formation** | `incident-formation` | ✅ Complete | Severity routing, persistence, BullMQ queue, idempotency |
| **Adaptive Sampling** | `adaptive-sampling` | ✅ Complete | 1-in-N window sampling for healthy executions |
| **Database** | `@void-server/db` | ✅ Complete | Prisma schema, migrations, Incident 1:N Report |
| **Node API** | `node-api` | ✅ Complete | Express server, CRUD endpoints, BullMQ worker → Python subprocess |
| **FastAPI Service** | `fastapi-api` | ✅ Complete | Mirror API for Python-side access |
| **AI Evaluator** | `evaluator` (Python) | ✅ Complete | Gemini-powered failure mode detection, confidence scoring, 16-schema evaluation |
| **Issue Agent** | `issue-agent` (Python) | ✅ Complete | Repository investigation, code graph, timeline reconstruction, GitHub issue generation |
| **Test Scenarios** | `evaluation_dataset` | ✅ Complete | 16 incident scenarios covering all failure modes |
| **Infrastructure** | Docker Compose | ✅ Complete | PostgreSQL 16, Redis 7, Adminer, service Dockerfiles |
| **CI/CD** | turbo.json | ✅ Complete | Build pipeline, workspace orchestration |

---

## Project Stats

- **Languages:** TypeScript (~5,000 LOC) + Python (~3,500 LOC)
- **Packages:** 9 total (5 TS + 2 Python packages + 2 apps)
- **Tests:** ~180 unit/integration tests across all packages
- **Incident Evaluation Dataset:** 16 scenarios (example, context-overflow, handoff-failure, looping, tool-anomaly, crash-loop, critical-escalation, false-positive, insufficient-evidence, mixed-labels, rate-limit, recurring, transient-error, silent-hallucination, near-perfect, ambiguous-edge-case)
- **AI Models:** Google Gemini 3.1 Flash Lite (evaluator + issue agent)
- **Infrastructure:** PostgreSQL 16 (port 5435), Redis 7 (port 6379)

---

## Database Schema (`Incidents` 1:N `Reports`)

- **`incidents`**: `id`, `fingerprint` (unique), `trace_id`, `execution_id`, `title`, `severity`, `status`, `confidence`, `first_scene`, `last_scene`, `latest_report_id`, `occurrence`, `last_seen`, `analysis_status` (PENDING/PROCESSING/COMPLETED/FAILED), `latest_labels` (JSONB), `agent_steps` (JSON), `telemetry` (JSON), `engineering_report` (JSONB), `issue_url`, `created_at`, `updated_at`.
- **`reports`**: `id`, `incident_id` (FK), `model`, `report` (JSONB), `generated_at`.

---

## Incident Formation Rules

| Severity | Persisted? | Queued? | Job Name |
|---|---|---|---|
| HEALTHY | No (sampled 1-in-N) | Sampled to queue | `adaptive-sampling` |
| SUSPICIOUS | Yes | Yes (on creation) | `evaluate-incident` |
| CRITICAL | Yes | Yes (on creation / escalation) | `critical-incident` |

---

## Quickstart

### Docker (Recommended)

```bash
docker build -t void-server .

# Run API
docker run -d --name void-api \
  -p 3001:3001 \
  -e SERVICE=api \
  -e DATABASE_URL=postgresql://void:voidpass@host.docker.internal:5432/void_db \
  -e REDIS_URL=redis://host.docker.internal:6379 \
  void-server

# Run Worker
docker run -d --name void-worker \
  -e SERVICE=worker \
  -e DATABASE_URL=postgresql://void:voidpass@host.docker.internal:5432/void_db \
  -e REDIS_URL=redis://host.docker.internal:6379 \
  -e GOOGLE_API_KEY=your-key \
  void-server

# Run Sampling Consumer
docker run -d --name void-sampling \
  -e SERVICE=sampling-consumer \
  -e DATABASE_URL=postgresql://void:voidpass@host.docker.internal:5432/void_db \
  -e REDIS_URL=redis://host.docker.internal:6379 \
  -e GOOGLE_API_KEY=your-key \
  void-server
```

Stop:

```bash
docker stop void-api void-worker void-sampling
docker rm void-api void-worker void-sampling
```

### Local Development

#### 1. Configure Environment & Start Infrastructure

```bash
cp .env.example .env
npm run db:up
```

- PostgreSQL: `localhost:5435` (User: `void`, Pass: `voidpass`, DB: `void_db`)
- Redis: `localhost:6379`
- Adminer: http://localhost:8088

#### 2. Database Migrations

```bash
npm run db:push
```

#### 3. Run Development Servers

```bash
npm run dev                                      # All workspaces via Turborepo
npm run dev --workspace=@void-server/node-api    # Node API only (port 3001)
cd apps/fastapi-api && pip install -r requirements.txt && python main.py  # FastAPI (port 8000)
```

#### 4. Stop Infrastructure

```bash
npm run db:down
```

### 4. Run All Tests

```bash
# TypeScript packages (vitest)
npm test --workspace=@void-server/risk-engine
npm test --workspace=@void-server/incident-fingerprint
npm test --workspace=@void-server/incident-formation
npm test --workspace=@void-server/adaptive-sampling

# Python packages (unittest) — issue agent
PYTHONPATH=packages/issue-agent/src:packages/evaluator/src:packages/issue-agent/tests \
  python3 -m unittest discover -s packages/issue-agent/tests -p "test_*.py" -v
```

### 5. Issue Agent E2E Monitoring

```bash
# Requires GOOGLE_API_KEY in .env
pip install -e packages/evaluator -e packages/issue-agent
python3 packages/issue-agent/tests/e2e_monitor.py

# Run specific scenarios
python3 packages/issue-agent/tests/e2e_monitor.py example tool-anomaly
```

### 6. Run Evaluator CLI

```bash
echo '{"id":"test","execution_id":"test","trace_id":"test","severity":"SUSPICIOUS","status":"OPEN","confidence":0,"occurrence":1,"analysis_status":"PENDING","agent_steps":[],"telemetry":null}' | \
  PYTHONPATH=packages/evaluator/src python3 -m evaluator
```

### 7. Run Issue Agent CLI (Dev Mode)

```bash
cat evaluation_dataset/incidents/example/incident.json | \
  PYTHONPATH=packages/issue-agent/src VOID_DEV_MODE=1 python3 -m issue_agent
```
