# void-server

> **Turborepo Monorepo with Dockerized PostgreSQL + Redis, Node.js (Express), and Python (FastAPI)**

---

## 📁 Monorepo Structure

```
void-server/
├── docker-compose.yml           # PostgreSQL 16, Redis 7, Adminer
├── turbo.json                   # Turborepo task runner configuration
├── package.json                 # npm workspaces root configuration
├── .env.example                 # Environment variables template
│
├── apps/
│   ├── node-api/                # Node.js TypeScript + Express API (Port 3001)
│   │   └── src/index.ts         # Express server & Prisma database queries
│   │
│   └── fastapi-api/             # Python FastAPI Service (Port 8000)
│       ├── main.py              # FastAPI app & endpoints
│       ├── database.py          # SQLAlchemy session setup
│       ├── models.py            # Incidents & Reports ORM models
│       └── requirements.txt
│
└── packages/
    ├── db/                      # Shared Database Package (Prisma ORM)
    │   └── prisma/schema.prisma # Incidents 1:N Reports schema definition
    │
    ├── risk-engine/             # Deterministic risk evaluation engine
    │   └── src/
    │       ├── evaluator.ts     # Orchestrator: 8 policy checks → risk labels
    │       ├── types.ts         # RiskLabel enum (10 values), Execution, config types
    │       └── policies/        # 8 pure policy functions (latency, tokens, crashes...)
    │
    ├── incident-fingerprint/    # SHA-256 incident fingerprinting
    │   └── src/
    │       ├── risk-labels.ts   # normalizeRiskLabels() — validate, dedup, sort
    │       ├── incident-fingerprint.ts  # generateFingerprint() — SHA-256 hex hash
    │       └── types.ts         # RiskLabel enum (10 values), Severity type
    │
    └── incident-formation/      # Incident persistence + BullMQ queue
        └── src/
            ├── service.ts       # IncidentFormationService — severity-routed orchestration
            ├── repository.ts    # PrismaIncidentRepository — CRUD via fingerprint
            ├── queue.ts         # BullMqIncidentQueue — Redis-backed, stable jobId
            └── types.ts         # IncidentInput, ProcessResult, interfaces
```

---

## 🗄️ Database Schema Design (`Incidents` 1 ➔ N `Reports`)

- **`incidents`**: `id`, `fingerprint` (unique), `trace_id`, `execution_id`, `title`, `severity`, `status`, `confidence`, `first_scene`, `last_scene`, `latest_report_id`, `occurrence`, `last_seen`, `analysis_status`, `latest_labels` (JSONB), `created_at`, `updated_at`.
- **`reports`**: `id`, `incident_id` (FK), `model`, `report` (JSONB), `generated_at`.

---

## 🔄 Pipeline

```
Risk Evaluation Result
        ↓
normalizeRiskLabels()    [packages/incident-fingerprint]
        ↓
generateFingerprint()    [packages/incident-fingerprint]
        ↓
IncidentFormationService  [packages/incident-formation]
        ↓
    ┌────┼────┐
    │    │    │
HEALTHY SUSPICIOUS CRITICAL
    │     │         │
  skip  persist    persist
        queue      queue
"evaluate-incident" "critical-incident"
```

---

## ⚡ Quickstart

### 1. Configure Environment & Start Infrastructure
```bash
# Create local environment config
cp .env.example .env

# Start database & Redis infrastructure for local dev
npm run db:up
```
- **PostgreSQL**: `localhost:5435` (User: `void`, Pass: `voidpass`, DB: `void_db`)
- **Redis**: `localhost:6379`
- **Adminer**: [http://localhost:8088](http://localhost:8088)

### 2. Run Database Migrations / Push Schema
```bash
npm run db:push
```

### 3. Run Development Servers
```bash
# Run all workspaces via Turborepo
npm run dev

# Or run specific workspace
npm run dev --workspace=@void-server/node-api

# Or run FastAPI Service (Port 8000)
cd apps/fastapi-api && pip install -r requirements.txt && python main.py
```

### 4. Run Tests
```bash
# All packages
npm test --workspace=@void-server/risk-engine
npm test --workspace=@void-server/incident-fingerprint
npm test --workspace=@void-server/incident-formation
```

### 5. Issue Agent E2E Monitoring
```bash
# Requires GOOGLE_API_KEY in .env

# Run all 14 scenarios (produces full report per scenario)
packages/evaluator/.venv/bin/python3 packages/issue-agent/tests/e2e_monitor.py

# Run specific scenario(s)
packages/evaluator/.venv/bin/python3 packages/issue-agent/tests/e2e_monitor.py example tool-anomaly

# Run issue agent unit tests
python3 -m pytest packages/issue-agent/tests/ -k "not e2e"
```

---

## 🧩 Packages

| Package | Responsibility |
|---|---|
| `@void-server/risk-engine` | Evaluates executions against 8 deterministic policies → risk labels |
| `@void-server/incident-fingerprint` | Normalizes labels, generates SHA-256 fingerprint |
| `@void-server/incident-formation` | Persists incidents, queues analysis via BullMQ |
| `@void-server/db` | Prisma client, shared database types |

### Incident Formation Rules

| Severity | Persisted? | Queued? | Job Name |
|---|---|---|---|
| HEALTHY | No | No | — |
| SUSPICIOUS | Yes | Yes (on creation) | `evaluate-incident` |
| CRITICAL | Yes | Yes (on creation / escalation) | `critical-incident` |
