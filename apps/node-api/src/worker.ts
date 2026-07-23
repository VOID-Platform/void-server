import { Worker, Job } from "bullmq";
import { execFile } from "child_process";
import { db } from "./db";

const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379";
const EVALUATOR_TIMEOUT_MS = parseInt(process.env.EVALUATOR_TIMEOUT_MS ?? "120000", 10);
const EVALUATOR_PYTHON = process.env.EVALUATOR_PYTHON ?? "python3";
const EVALUATOR_MODULE = process.env.EVALUATOR_MODULE ?? "evaluator";
const EVALUATOR_PYTHONPATH = process.env.EVALUATOR_PYTHONPATH ?? "";

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

function runEvaluator(incidentJson: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      EVALUATOR_PYTHON,
      ["-m", EVALUATOR_MODULE],
      {
        env: {
          ...process.env,
          ...(EVALUATOR_PYTHONPATH ? { PYTHONPATH: EVALUATOR_PYTHONPATH } : {}),
        },
        maxBuffer: 1024 * 1024,
        timeout: EVALUATOR_TIMEOUT_MS,
      },
      (err, stdout, stderr) => {
        if (err) {
          reject(new Error(`Evaluator exited: ${err.message}\nStderr: ${stderr}`));
          return;
        }
        resolve(stdout.trim());
      },
    );
    child.stdin?.write(incidentJson);
    child.stdin?.end();
  });
}

async function processJob(job: Job<{ incidentId: string }, void, string>) {
  const { incidentId } = job.data;
  console.log(`[worker] processing incident ${incidentId} (job ${job.id})`);

  const incident = await db.incident.findUnique({
    where: { id: incidentId },
  });
  if (!incident) {
    throw new Error(`Incident ${incidentId} not found`);
  }

  await db.incident.update({
    where: { id: incidentId },
    data: { analysis_status: "PROCESSING" },
  });

  const reportData: Record<string, unknown> = {
    id: incident.id,
    fingerprint: incident.fingerprint,
    trace_id: incident.trace_id,
    execution_id: incident.execution_id,
    title: incident.title,
    severity: incident.severity,
    status: incident.status,
    confidence: incident.confidence,
    first_scene: incident.first_scene,
    last_scene: incident.last_scene,
    occurrence: incident.occurrence,
    analysis_status: incident.analysis_status,
    latest_labels: incident.latest_labels,
    execution_status: "COMPLETED",
    agent_steps: (incident as any).agent_steps ?? [],
    telemetry: (incident as any).telemetry ?? null,
  };

  let raw: string;
  let parsed: Record<string, unknown>;
  try {
    raw = await runEvaluator(JSON.stringify(reportData));
    parsed = JSON.parse(raw);
  } catch (err) {
    await db.incident.update({
      where: { id: incidentId },
      data: { analysis_status: "FAILED" },
    });
    console.error(`[worker] evaluator execution failed for ${incidentId}:`, (err as Error).message);
    return;
  }

  if (parsed.error) {
    await db.incident.update({
      where: { id: incidentId },
      data: { analysis_status: "FAILED" },
    });
    console.error(`[worker] evaluator failed for ${incidentId}: ${parsed.error}`);
    return;
  }

  const evaluation = parsed.evaluation as Record<string, unknown>;
  const metadata = parsed.metadata as Record<string, unknown>;

  try {
    await db.$transaction(async (tx) => {
      const report = await tx.report.create({
        data: {
          incident_id: incidentId,
          model: (metadata.model_version as string) ?? "",
          report: parsed as object,
        },
      });

      await tx.incident.update({
        where: { id: incidentId },
        data: {
          analysis_status: "COMPLETED",
          confidence: evaluation.confidence as number,
          latest_report_id: report.id,
        },
      });
    });
  } catch (err) {
    await db.incident.update({
      where: { id: incidentId },
      data: { analysis_status: "FAILED" },
    });
    console.error(`[worker] persistence failed for ${incidentId}:`, (err as Error).message);
    throw err;
  }

  console.log(
    `[worker] completed ${incidentId}: ${String(evaluation.classification)} (confidence: ${String(evaluation.confidence)})`,
  );
}

const connection = parseRedisUrl(REDIS_URL);
const worker = new Worker("incident-analysis", processJob, {
  connection,
  concurrency: 1,
  autorun: true,
});

worker.on("completed", (job) => {
  console.log(`[worker] job ${job?.id} completed`);
});

worker.on("failed", (job, err) => {
  console.error(`[worker] job ${job?.id} failed:`, err.message);
});

async function shutdown() {
  console.log("[worker] shutting down gracefully...");
  await worker.close();
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

console.log("[worker] listening on incident-analysis queue");
