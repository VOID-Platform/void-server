import { Worker, Job } from "bullmq";
import { runPythonModule } from "./python";
import { db } from "./db";
import { IncidentFormationService, PrismaIncidentRepository, BullMqIncidentQueue } from "@void-server/incident-formation";
import { createHash } from "node:crypto";

const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379";
const EVALUATOR_TIMEOUT_MS = parseInt(process.env.EVALUATOR_TIMEOUT_MS ?? "120000", 10);
const EVALUATOR_MODULE = process.env.EVALUATOR_MODULE ?? "evaluator";
const PROMOTION_CONFIDENCE_THRESHOLD = parseFloat(process.env.PROMOTION_CONFIDENCE_THRESHOLD ?? "0.7");

const formationService = new IncidentFormationService(
  new PrismaIncidentRepository(db),
  new BullMqIncidentQueue()
);

function parseRedisUrl(urlStr: string) {
  const parsed = new URL(urlStr);
  if (!parsed.hostname) throw new Error(`Invalid REDIS_URL: no hostname in "${urlStr}"`);
  const config: Record<string, unknown> = {
    host: parsed.hostname,
    port: parsed.port ? parseInt(parsed.port, 10) : 6379,
  };
  if (parsed.username) config.username = decodeURIComponent(parsed.username);
  if (parsed.password) config.password = decodeURIComponent(parsed.password);
  const dbIndex = parsed.pathname ? parseInt(parsed.pathname.replace("/", ""), 10) : NaN;
  if (!isNaN(dbIndex)) config.db = dbIndex;
  if (parsed.protocol === "rediss:") config.tls = {};
  return config;
}

async function processSample(job: Job) {
  const sample = job.data as {
    executionId: string;
    traceId?: string;
    timestamp: string;
    agentSteps?: unknown[];
    telemetry?: Record<string, unknown>;
  };
  console.log(`[sampling] evaluating sampled execution ${sample.executionId}`);

  const input = {
    id: sample.executionId,
    execution_id: sample.executionId,
    trace_id: sample.traceId ?? "",
    severity: "HEALTHY",
    status: "OPEN",
    confidence: 0,
    occurrence: 1,
    analysis_status: "PENDING",
    agent_steps: sample.agentSteps ?? [],
    telemetry: sample.telemetry ?? null,
  };

  let raw: string;
  try {
    raw = await runPythonModule(EVALUATOR_MODULE, JSON.stringify(input), EVALUATOR_TIMEOUT_MS);
  } catch (err) {
    console.error(`[sampling] evaluator failed for ${sample.executionId}:`, (err as Error).message);
    return;
  }

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(raw);
  } catch {
    console.error(`[sampling] invalid evaluator output for ${sample.executionId}`);
    return;
  }

  if (parsed.error) {
    console.error(`[sampling] evaluator error for ${sample.executionId}: ${parsed.error}`);
    return;
  }

  const evaluation = parsed.evaluation as Record<string, unknown> | undefined;
  if (!evaluation) {
    console.log(`[sampling] no evaluation for ${sample.executionId}, skipping`);
    return;
  }

  const classification = String(evaluation.classification ?? "");
  const confidence = Number(evaluation.confidence ?? 0);
  const failureModes = (evaluation.failure_modes as string[]) ?? [];

  const promoted = classification === "REAL_INCIDENT" && confidence >= PROMOTION_CONFIDENCE_THRESHOLD && failureModes.length > 0 && !failureModes.includes("NONE_DETECTED");

  if (!promoted) {
    console.log(`[sampling] skipped ${sample.executionId}: ${classification} (confidence: ${confidence})`);
    return;
  }

  console.log(`[sampling] promoting ${sample.executionId} to incident`);

  const fingerprint = createHash("sha256")
    .update(failureModes.sort().join("|"))
    .digest("hex");

  await formationService.process({
    fingerprint,
    severity: "SUSPICIOUS",
    labels: [],
    executionId: sample.executionId,
    traceId: sample.traceId,
    timestamp: new Date(sample.timestamp),
    agent_steps: sample.agentSteps,
    telemetry: sample.telemetry,
  });

  console.log(`[sampling] promoted ${sample.executionId} to incident pipeline`);
}

const connection = parseRedisUrl(REDIS_URL);
const worker = new Worker("adaptive-sampling", processSample, {
  connection,
  concurrency: 1,
  autorun: true,
});

worker.on("completed", (job) => {
  console.log(`[sampling] job ${job?.id} completed`);
});

worker.on("failed", (job, err) => {
  console.error(`[sampling] job ${job?.id} failed:`, err.message);
});

async function shutdown() {
  console.log("[sampling] shutting down...");
  await worker.close();
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

console.log("[sampling] listening on adaptive-sampling queue");