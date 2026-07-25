import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(process.cwd(), '../void/.env') });
dotenv.config({ path: path.resolve(process.cwd(), '.env') });

if (!process.env.DATABASE_URL) {
  process.env.DATABASE_URL = 'postgresql://void:voidpass@localhost:5432/void_db?schema=public';
}
import { db } from './db';
import { evaluate } from "@void-server/risk-engine";
import { config as defaultRiskConfig } from "@void-server/risk-engine";
import { normalizeRiskLabels } from "@void-server/incident-fingerprint";
import { IncidentFormationService, PrismaIncidentRepository, BullMqIncidentQueue } from "@void-server/incident-formation";
import { AdaptiveSamplingService, BullMqSamplingQueue } from "@void-server/adaptive-sampling";

import IORedis from "ioredis";

const REDIS_URL = process.env.REDIS_URL || "redis://localhost:6379";
const app = express();
const PORT = Number(process.env.NODE_API_PORT) || 3001;

app.use(cors());
app.use(express.json());

const repo = new PrismaIncidentRepository(db);
const queue = new BullMqIncidentQueue();
const formationService = new IncidentFormationService(repo, queue);
const samplingQueue = new BullMqSamplingQueue();
const sampler = new AdaptiveSamplingService(samplingQueue, {});

// Healthcheck endpoint verifying PostgreSQL database connection
app.get('/health', async (_req, res) => {
  try {
    await db.$queryRaw`SELECT 1`;
    res.json({ status: 'ok', service: 'node-api', database: 'connected' });
  } catch (error) {
    res.status(500).json({ status: 'error', database: 'disconnected', details: String(error) });
  }
});

// Fetch all incidents with associated reports
app.get('/api/incidents', async (_req, res) => {
  try {
    const incidents = await db.incident.findMany({
      include: { reports: true },
      orderBy: { created_at: 'desc' },
    });
    res.json({ count: incidents.length, data: incidents });
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch incidents', details: String(error) });
  }
});

// Look up incidents by SDK execution_id
app.get('/api/incidents/by-execution/:executionId', async (req, res) => {
  try {
    const incidents = await db.incident.findMany({
      where: { execution_id: req.params.executionId },
      include: { reports: true },
      orderBy: { created_at: 'desc' },
    });
    res.json({ count: incidents.length, data: incidents });
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch incidents', details: String(error) });
  }
});

// Poll investigation status for a specific incident (used by demo frontend)
app.get('/api/investigations/:incidentId', async (req, res) => {
  try {
    const incident = await db.incident.findUnique({
      where: { id: req.params.incidentId },
      include: { reports: { orderBy: { generated_at: 'desc' }, take: 1 } },
    });
    if (!incident) return res.status(404).json({ error: 'Incident not found' });

    const s = incident.analysis_status;
    if (s === 'PENDING') return res.json({ status: 'QUEUED' });
    if (s === 'PROCESSING') return res.json({ status: 'PROCESSING' });
    if (s === 'FAILED') {
      const engReport = incident.engineering_report as Record<string, unknown> | null;
      const errDetail = (engReport?.error as string) ?? 'Worker failed during LLM evaluation';
      return res.json({ status: 'FAILED', error: errDetail });
    }

    // COMPLETED
    return res.json({
      status: 'COMPLETED',
      incidentId: incident.id,
      severity: incident.severity,
      labels: incident.latest_labels ?? [],
      confidence: incident.confidence,
      evaluation: incident.reports[0]?.report ?? null,
      engineeringReport: incident.engineering_report ?? null,
      issueUrl: incident.issue_url ?? null,
    });
  } catch (err) {
    return res.status(500).json({ error: 'Internal server error', details: String(err) });
  }
});

// Look up incidents by OpenTelemetry trace_id (correlates with SigNoz)
app.get('/api/incidents/by-trace/:traceId', async (req, res) => {
  try {
    const incidents = await db.incident.findMany({
      where: { trace_id: req.params.traceId },
      include: { reports: true },
      orderBy: { created_at: 'desc' },
    });
    res.json({ count: incidents.length, data: incidents });
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch incidents', details: String(error) });
  }
});

// Create or update an incident
app.post('/api/incidents', async (req, res) => {
  try {
    const {
      fingerprint,
      trace_id,
      execution_id,
      title,
      severity,
      status,
      confidence,
      first_scene,
      last_scene,
      agent_steps,
      telemetry,
    } = req.body;

    const incident = await db.incident.upsert({
      where: { fingerprint },
      update: {
        occurrence: { increment: 1 },
        last_scene,
        status,
        ...(agent_steps !== undefined ? { agent_steps } : {}),
        ...(telemetry !== undefined ? { telemetry } : {}),
      },
      create: {
        fingerprint,
        trace_id,
        execution_id,
        title,
        severity,
        status,
        confidence,
        first_scene,
        last_scene,
        ...(agent_steps !== undefined ? { agent_steps } : {}),
        ...(telemetry !== undefined ? { telemetry } : {}),
      },
    });

    res.status(201).json({ status: 'success', data: incident });
  } catch (error) {
    res.status(500).json({ error: 'Failed to save incident', details: String(error) });
  }
});

// Clear database and flush Redis queues for demo reset
app.post('/api/admin/reset', async (_req, res) => {
  try {
    console.log('[admin] 🧹 Resetting PostgreSQL database and Redis queues...');
    await db.report.deleteMany({});
    await db.incident.deleteMany({});
    const redis = new IORedis(REDIS_URL);
    await redis.flushall();
    redis.disconnect();
    console.log('[admin] ✅ DB and Redis flushed!');
    res.json({ success: true, message: 'Database and BullMQ queue reset successfully.' });
  } catch (error) {
    console.error('[admin] ❌ Reset error:', error);
    res.status(500).json({ error: 'Failed to reset state', details: String(error) });
  }
});

// ponytail: normalize flat {tool_name, success} steps from the demo into the
// structured {step_type, tool_calls: [{name, success}]} format the Python
// evaluator and issue-agent Pydantic schemas require
function normalizeAgentSteps(steps: any[]): any[] {
  if (!steps || steps.length === 0) return [];
  if ("tool_calls" in steps[0] || "step_type" in steps[0]) return steps;
  return steps.map((s, i) => ({
    step_type: "tool_execution",
    step_number: i,
    tool_calls: [
      {
        name: s.tool_name ?? "unknown",
        success: s.success ?? true,
        latency_ms: s.latency_ms ?? null,
        error: s.error ?? undefined,
        input: typeof s.input === 'object' && s.input !== null ? JSON.stringify(s.input) : (s.input ?? undefined),
      },
    ],
    latency_ms: s.latency_ms ?? null,
  }));
}

app.post("/api/traces", async (req, res) => {
  try {
    const body = req.body;
    if (!body.execution_id) {
      return res.status(400).json({ error: "execution_id is required" });
    }

    const execution = {
      latencyMs: body.total_latency_ms ?? 0,
      promptTokens: body.total_prompt_tokens ?? 0,
      completionTokens: body.total_completion_tokens ?? 0,
      toolExecutions: (body.steps ?? []).map((s: any) => ({
        toolName: s.tool_name ?? "unknown",
        success: s.success ?? true,
      })),
      retryCount: body.retry_count ?? 0,
      hasFinalResponse: body.crashed !== true,
      crashed: body.crashed ?? false,
      contextWindowExceeded: body.context_window_exceeded ?? false,
    };

    const risk = evaluate(execution, defaultRiskConfig);
    const labels = normalizeRiskLabels({ severity: risk.severity as any, labels: risk.labels });
    const timestamp = new Date();
    const agentSteps = normalizeAgentSteps(body.steps ?? []);
    const telemetry = {
      total_latency_ms: body.total_latency_ms,
      total_prompt_tokens: body.total_prompt_tokens,
      total_completion_tokens: body.total_completion_tokens,
      tool_call_count: agentSteps.length,
      failed_tool_calls: agentSteps.filter((s: any) => {
        const tc = s.tool_calls ?? [];
        return tc.some((t: any) => t.success === false);
      }).length,
      retry_count: body.retry_count,
    };

    console.log(`[node-api] 📥 Trace ingested: exec=${body.execution_id} trace=${body.trace_id ?? 'none'} latency=${body.total_latency_ms ?? 0}ms tokens=${(body.total_prompt_tokens ?? 0) + (body.total_completion_tokens ?? 0)}`);
    console.log(`[node-api] 🛡️ Risk engine outcome: exec=${body.execution_id} -> severity=${risk.severity} labels=[${labels.join(', ')}]`);

    if (risk.severity === "HEALTHY") {
      const sampled = await sampler.process({
        executionId: body.execution_id,
        traceId: body.trace_id,
        timestamp,
        agentSteps,
        telemetry,
      });
      console.log(`[node-api] ⚡ Adaptive sampler result: exec=${body.execution_id} sampled=${sampled}`);
      return res.status(200).json({
        status: "healthy",
        execution_id: body.execution_id,
        severity: "HEALTHY",
        labels,
        sampled,
      });
    }

    const result = await formationService.process({
      severity: risk.severity,
      labels,
      executionId: body.execution_id,
      traceId: body.trace_id,
      timestamp,
      agent_steps: agentSteps,
      telemetry,
    });

    const incidentId = result.action !== "SKIPPED" ? result.incident.id : undefined;
    console.log(`[node-api] 📋 Incident formation result: exec=${body.execution_id} -> action=${result.action} incidentId=${incidentId ?? 'none'}`);

    return res.status(result.action === "CREATED" ? 201 : 200).json({
      status: result.action === "CREATED" ? "incident_created" : "incident_updated",
      execution_id: body.execution_id,
      severity: risk.severity,
      labels,
      incident_id: incidentId,
    });

  } catch (err) {
    console.error("[traces] error:", err);
    return res.status(500).json({ error: "Internal server error" });
  }
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`🚀 Node.js API running at http://0.0.0.0:${PORT}`);
});
