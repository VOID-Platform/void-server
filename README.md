# void-server

> **Turborepo Monorepo with Dockerized PostgreSQL, Node.js (Express), and Python (FastAPI)**

---

## 📁 Monorepo Structure

```
void-server/
├── docker-compose.yml           # PostgreSQL 16 & Adminer database containers
├── turbo.json                   # Turborepo task runner configuration
├── package.json                 # npm workspaces root configuration
├── .env                         # Database & service environment variables
│
├── apps/
│   ├── node-api/                # Node.js TypeScript + Express API (Port 3001)
│   │   ├── src/index.ts         # Express server & Prisma database queries
│   │   └── package.json
│   │
│   └── fastapi-api/             # Python FastAPI Service (Port 8000)
│       ├── main.py              # FastAPI app & endpoints
│       ├── database.py          # SQLAlchemy session setup
│       ├── models.py            # Incidents & Reports ORM models
│       └── requirements.txt
│
└── packages/
    └── db/                      # Shared Database Package (Prisma ORM)
        └── prisma/
            └── schema.prisma    # Incidents 1:N Reports schema definition
```

---

## 🗄️ Database Schema Design (`Incidents` 1 ➔ N `Reports`)

- **`incidents`**: `id`, `fingerprint` (unique), `trace_id`, `execution_id`, `title`, `severity`, `status`, `confidence`, `first_scene`, `last_scene`, `latest_report_id`, `occurrence`, `created_at`, `updated_at`.
- **`reports`**: `id`, `incident_id` (FK), `model`, `report` (JSONB), `generated_at`.

---

## ⚡ Quickstart

### 1. Start Dockerized PostgreSQL
```bash
npm run db:up
```
- **PostgreSQL**: `localhost:5432` (User: `void`, Pass: `voidpass`, DB: `void_db`)
- **Adminer DB Web UI**: [http://localhost:8080](http://localhost:8080)

### 2. Run Database Migrations / Push Schema
```bash
npm run db:push
```

### 3. Run Development Servers
```bash
# Run all workspaces via Turborepo
npm run dev

# Or run Node.js API (Port 3001)
npm run dev --workspace=@void-server/node-api

# Or run FastAPI Service (Port 8000)
cd apps/fastapi-api
pip install -r requirements.txt
python main.py
```
