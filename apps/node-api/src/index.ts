import express from 'express';
import cors from 'cors';
import { db } from './db';
import { evaluate } from "@void-server/risk-engine";
import { config as defaultRiskConfig } from "@void-server/risk-engine";
import { normalizeRiskLabels } from "@void-server/incident-fingerprint";
import { IncidentFormationService, PrismaIncidentRepository, BullMqIncidentQueue } from "@void-server/incident-formation";
import { AdaptiveSamplingService, BullMqSamplingQueue } from "@void-server/adaptive-sampling";

const app = express();
const PORT = process.env.NODE_API_PORT || 3001;

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
    const agentSteps = body.steps ?? [];
    const telemetry = {
      total_latency_ms: body.total_latency_ms,
      total_prompt_tokens: body.total_prompt_tokens,
      total_completion_tokens: body.total_completion_tokens,
      tool_call_count: agentSteps.length,
      failed_tool_calls: agentSteps.filter((s: any) => !s.success).length,
      retry_count: body.retry_count,
    };

    if (risk.severity === "HEALTHY") {
      const sampled = await sampler.process({
        executionId: body.execution_id,
        traceId: body.trace_id,
        timestamp,
        agentSteps,
        telemetry,
      });
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

app.listen(PORT, () => {
  console.log(`🚀 Node.js API running at http://localhost:${PORT}`);
});
