import { Worker, Job } from "bullmq";
import { runPythonModule } from "./python";
import { db } from "./db";

const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379";
const EVALUATOR_TIMEOUT_MS = parseInt(process.env.EVALUATOR_TIMEOUT_MS ?? "120000", 10);
const EVALUATOR_MODULE = process.env.EVALUATOR_MODULE ?? "evaluator";
const ISSUE_AGENT_MODULE = process.env.ISSUE_AGENT_MODULE ?? "issue_agent";
const PROMOTION_CONFIDENCE_THRESHOLD = parseFloat(process.env.PROMOTION_CONFIDENCE_THRESHOLD ?? "0.7");
const ISSUE_AGENT_TIMEOUT_MS = parseInt(process.env.ISSUE_AGENT_TIMEOUT_MS ?? "180000", 10);

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
  return runPythonModule(EVALUATOR_MODULE, incidentJson, EVALUATOR_TIMEOUT_MS);
}

function runIssueAgent(snapshotJson: string): Promise<string> {
  return runPythonModule(ISSUE_AGENT_MODULE, snapshotJson, ISSUE_AGENT_TIMEOUT_MS);
}

export function shouldPromoteToIssueAgent(
  jobName: string,
  classification: string,
  confidence: number,
  failureModes: string[],
): boolean {
  if (jobName === "critical-incident") return true;
  return classification === "REAL_INCIDENT" && confidence >= PROMOTION_CONFIDENCE_THRESHOLD && failureModes.length > 0 && !failureModes.includes("NONE_DETECTED");
}

async function processJob(job: Job<{ incidentId: string }, void, string>) {
  const { incidentId } = job.data;
  console.log(`[worker] processing incident ${incidentId} (job ${job.id}, type ${job.name})`);

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

  const evaluation = parsed.evaluation as Record<string, unknown> | undefined;
  if (!evaluation) {
    await db.incident.update({
      where: { id: incidentId },
      data: { analysis_status: "FAILED" },
    });
    console.error(`[worker] evaluator returned no evaluation for ${incidentId}`);
    return;
  }
  const metadata = (parsed.metadata as Record<string, unknown>) ?? {};

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
    `[worker] evaluated ${incidentId}: ${String(evaluation.classification)} (confidence: ${String(evaluation.confidence)})`,
  );

  if (!shouldPromoteToIssueAgent(
    job.name,
    String(evaluation.classification ?? ""),
    Number(evaluation.confidence ?? 0),
    (evaluation.failure_modes as string[]) ?? [],
  )) {
    console.log(`[worker] skipped issue agent for ${incidentId} (below promotion threshold)`);
    return;
  }

  console.log(`[worker] promoting ${incidentId} to issue agent`);
  let issueOutput: string;
  try {
    const snapshot = {
      incident_id: incidentId,
      execution_trace: {
        agent_steps: (incident as any).agent_steps ?? [],
        model: (metadata.model_version as string) ?? "",
        total_latency_ms: (reportData.telemetry as any)?.total_latency_ms ?? null,
        tokens_used: (reportData.telemetry as any)?.total_prompt_tokens != null
          ? (reportData.telemetry as any).total_prompt_tokens + ((reportData.telemetry as any)?.total_completion_tokens ?? 0)
          : null,
      },
      evaluation: {
        failure_modes: (evaluation.failure_modes as string[]) ?? [],
        confidence: Number(evaluation.confidence ?? 0),
        reasoning: ((evaluation.reasoning as string[]) ?? []).join("\n"),
        urgency_tier: ((evaluation.urgency as Record<string, unknown>)?.tier as string) ?? "P2",
        severity: incident.severity === "CRITICAL" ? "CRITICAL" : "HIGH",
      },
      telemetry: (incident as any).telemetry ?? {},
      metadata: { incident_fingerprint: incident.fingerprint },
    };
    issueOutput = await runIssueAgent(JSON.stringify(snapshot));
  } catch (err) {
    console.error(`[worker] issue agent failed for ${incidentId}:`, (err as Error).message);
    return;
  }

  let engineeringReport: Record<string, unknown>;
  let issueUrl: string | null = null;
  try {
    const parsedIssue = JSON.parse(issueOutput);
    if (parsedIssue.issue_title) {
      engineeringReport = parsedIssue;
    } else if (typeof issueOutput === "string" && issueOutput.startsWith("GitHub issue created:")) {
      issueUrl = issueOutput.replace("GitHub issue created: ", "").trim();
      engineeringReport = {};
    } else {
      engineeringReport = {};
    }
  } catch {
    if (issueOutput.startsWith("GitHub issue created:")) {
      issueUrl = issueOutput.replace("GitHub issue created: ", "").trim();
      engineeringReport = {};
    } else {
      engineeringReport = { raw: issueOutput };
    }
  }

  await db.incident.update({
    where: { id: incidentId },
    data: {
      engineering_report: engineeringReport as object,
      ...(issueUrl ? { issue_url: issueUrl } : {}),
    },
  });

  console.log(`[worker] issue agent completed for ${incidentId}${issueUrl ? ` — ${issueUrl}` : ""}`);
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
