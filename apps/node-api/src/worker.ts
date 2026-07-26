import { Worker, Job } from "bullmq";
import { runPythonModule } from "./python";
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(process.cwd(), '../../.env') });
dotenv.config({ path: path.resolve(process.cwd(), '.env') });

process.env.DATABASE_URL = process.env.DATABASE_URL?.replace(/:5435\//, ':5432/') ?? 'postgresql://void:voidpass@localhost:5432/void_db?schema=public';
import { db } from "./db";

const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379";
const EVALUATOR_TIMEOUT_MS = parseInt(process.env.EVALUATOR_TIMEOUT_MS ?? "120000", 10);
const EVALUATOR_MODULE = process.env.EVALUATOR_MODULE ?? "evaluator";
const ISSUE_AGENT_MODULE = process.env.ISSUE_AGENT_MODULE ?? "issue_agent";
const PROMOTION_CONFIDENCE_THRESHOLD = parseFloat(process.env.PROMOTION_CONFIDENCE_THRESHOLD ?? "0.7");
const ISSUE_AGENT_TIMEOUT_MS = parseInt(process.env.ISSUE_AGENT_TIMEOUT_MS ?? "180000", 10);
const SIGNOZ_URL = process.env.SIGNOZ_URL ?? `http://localhost:${process.env.SIGNOZ_PORT ?? "8080"}`;

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

function normalizeAgentSteps(steps: any[]): any[] {
  if (!steps || steps.length === 0) return [];
  // Already normalized — pass through as-is, preserving all fields
  if ("tool_calls" in steps[0] || "step_type" in steps[0]) return steps;
  // Normalize legacy flat-object format, preserving planner_output and context
  return steps.map((s, i) => ({
    step_type: s.step_type ?? "tool_execution",
    step_number: i,
    // Preserve reasoning text so the issue agent can reconstruct what the agent intended
    planner_output: s.planner_output ?? s.reasoning ?? s.response ?? null,
    context: s.context ?? null,
    tool_calls: [
      {
        name: s.tool_name ?? "unknown",
        success: s.success ?? true,
        latency_ms: s.latency_ms ?? null,
        error: s.error ?? undefined,
        input: typeof s.input === 'object' && s.input !== null ? JSON.stringify(s.input) : (s.input ?? undefined),
        output: typeof s.output === 'object' && s.output !== null ? JSON.stringify(s.output) : (s.output ?? undefined),
      },
    ],
    latency_ms: s.latency_ms ?? null,
  }));
}

export function shouldPromoteToIssueAgent(
  jobName: string,
  classification: string,
  confidence: number,
  failureModes: string[],
): boolean {
  if (jobName === "critical-incident") return true;
  const isSemanticFailure = failureModes.some(m => {
    const mode = String(m).toUpperCase();
    return mode.includes("HALLUCINATION") || mode.includes("TOOL") || mode.includes("ANOMALY") || mode.includes("MISMATCH");
  });
  if (isSemanticFailure) return true;
  return classification === "REAL_INCIDENT" && confidence >= PROMOTION_CONFIDENCE_THRESHOLD && failureModes.length > 0 && !failureModes.includes("NONE_DETECTED");
}

async function processJob(job: Job<{ incidentId: string }, void, string>) {
  const { incidentId } = job.data;
  console.log(`[worker] 🚀 Job picked up: id=${job.id} type=${job.name} targetIncident=${incidentId}`);

  const incident = await db.incident.findUnique({
    where: { id: incidentId },
  });
  if (!incident) {
    console.error(`[worker] ❌ Incident ${incidentId} not found in PostgreSQL!`);
    throw new Error(`Incident ${incidentId} not found`);
  }

  await db.incident.update({
    where: { id: incidentId },
    data: { analysis_status: "PROCESSING" },
  });
  console.log(`[worker] 🔄 Incident ${incidentId} status updated: PENDING -> PROCESSING`);

  const steps = (incident as any).agent_steps ?? [];
  const stepCount = Array.isArray(steps) ? steps.length : 0;
  const stepKeys = stepCount > 0 ? Object.keys(steps[0] ?? {}).join(",") : "empty";
  console.log(`[worker] 📊 Incident telemetry context: steps=${stepCount} keys=[${stepKeys}] severity=${incident.severity}`);

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
    labels: incident.latest_labels ?? [],
    execution_status: "COMPLETED",
    agent_steps: (incident as any).agent_steps ?? [],
    telemetry: (incident as any).telemetry ?? null,
  };

  let raw: string;
  let parsed: Record<string, unknown>;
  try {
    console.log(`[worker] 🐍 Invoking Python module 'evaluator' via child process for ${incidentId}...`);
    raw = await runEvaluator(JSON.stringify(reportData));
    parsed = JSON.parse(raw);
    console.log(`[worker] ✅ Python evaluator returned output successfully for ${incidentId}`);
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    const isApiKeyError = errMsg.includes("API key not valid") || errMsg.includes("API_KEY_INVALID");
    const userFriendlyError = isApiKeyError
      ? "LLM Evaluator Error: Invalid GOOGLE_API_KEY. Please pass a valid Gemini API key to the worker."
      : `LLM Evaluator Error: ${errMsg}`;

    await db.incident.update({
      where: { id: incidentId },
      data: {
        analysis_status: "FAILED",
        engineering_report: { error: userFriendlyError } as object,
      },
    });
    console.error(`[worker] ❌ Evaluator execution failed for ${incidentId}:`, errMsg);
    return;
  }

  const evaluation = parsed.evaluation as Record<string, unknown> | undefined;
  if (!evaluation) {
    await db.incident.update({
      where: { id: incidentId },
      data: { analysis_status: "FAILED" },
    });
    console.error(`[worker] ❌ Evaluator returned no evaluation object for ${incidentId}`);
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
      console.log(`[worker] 💾 Persistence success: Report ${report.id} stored. Incident ${incidentId} marked COMPLETED.`);
    });
  } catch (err) {
    await db.incident.update({
      where: { id: incidentId },
      data: { analysis_status: "FAILED" },
    });
    console.error(`[worker] ❌ Database transaction failed for ${incidentId}:`, (err as Error).message);
    throw err;
  }

  const classif = String(evaluation.classification ?? "");
  const confNum = Number(evaluation.confidence ?? 0);
  const failModes = (evaluation.failure_modes as string[]) ?? [];
  console.log(
    `[worker] evaluated ${incidentId}: class=${classif} conf=${confNum} failures=[${failModes.join(",")}]`,
  );

  // ponytail: build a fallback engineering report from evaluation data so the UI
  // always has something to render, even without GOOGLE_API_KEY for the issue agent
  const fallbackReport: Record<string, unknown> = {
    summary: (evaluation.summary as string) ?? "",
    root_cause: (evaluation.suspected_root_cause as string) ?? (evaluation.summary as string) ?? "",
    evidence: (evaluation.reasoning as string[]) ?? [],
    suspected_components: (evaluation.suspected_components as string[]) ?? [],
    suggested_fix: ((evaluation.recommendations as string[]) ?? []).join("\n"),
    suggested_investigation: (evaluation.recommendations as string[]) ?? [],
    confidence: Number(evaluation.confidence ?? 0),
    executive_summary: `Incident: ${incident.title}`,
    impact: `Severity: ${incident.severity}. Classification: ${String(evaluation.classification ?? "N/A")}. Confidence: ${Number(evaluation.confidence ?? 0) * 100}%`,
    suggested_tests: [] as string[],
    relevant_files: [] as string[],
    relevant_functions: [] as string[],
    issue_title: incident.title,
    timeline: [] as object[],
    repository_findings: {} as object,
    evidence_analysis: "",
    secondary_effects: [] as string[],
    missing_context: null,
  };

  await db.incident.update({
    where: { id: incidentId },
    data: { engineering_report: fallbackReport as object },
  });

  const promote = shouldPromoteToIssueAgent(job.name, classif, confNum, failModes);
  console.log(
    `[worker] issue-agent check: job=${job.name} class=${classif} conf=${confNum} failures=[${failModes.join(",")}] threshold=${PROMOTION_CONFIDENCE_THRESHOLD} → ${promote ? 'PROMOTE' : 'skip'}`,
  );

  if (!promote) {
    console.log(`[worker] skipped issue agent for ${incidentId} (below promotion threshold)`);
    return;
  }

  console.log(`[worker] promoting ${incidentId} to issue agent`);
  let issueOutput: string;
  try {
    const snapshot = {
      incident_id: incidentId,
      execution_trace: {
        agent_steps: normalizeAgentSteps((incident as any).agent_steps ?? []),
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
      metadata: {
        incident_fingerprint: incident.fingerprint,
        // Pass evaluator-identified components so issue agent can anchor repo search
        suspected_components: (evaluation.suspected_components as string[]) ?? [],
        suspected_root_cause: (evaluation.suspected_root_cause as string) ?? "",
        incident_title: incident.title,
        // SigNoz trace link for direct observability correlation
        trace_id: incident.trace_id ?? "",
        signoz_trace_url: incident.trace_id
          ? `${SIGNOZ_URL}/trace/${incident.trace_id}`
          : "",
      },
    };
    issueOutput = await runIssueAgent(JSON.stringify(snapshot));
  } catch (err) {
    console.error(`[worker] issue agent failed for ${incidentId}:`, (err as Error).message);
    return;
  }

  let engineeringReport: Record<string, unknown> = fallbackReport;
  let issueUrl: string | null = null;
  try {
    const parsedIssue = JSON.parse(issueOutput);
    if (parsedIssue && typeof parsedIssue === "object") {
      engineeringReport = parsedIssue;
      if (parsedIssue.issue_url) {
        issueUrl = String(parsedIssue.issue_url);
      }
    } else if (typeof issueOutput === "string" && issueOutput.startsWith("GitHub issue created:")) {
      issueUrl = issueOutput.replace("GitHub issue created: ", "").trim();
    }
  } catch {
    if (typeof issueOutput === "string" && issueOutput.startsWith("GitHub issue created:")) {
      issueUrl = issueOutput.replace("GitHub issue created: ", "").trim();
    } else {
      engineeringReport = { ...fallbackReport, raw: issueOutput };
    }
  }

  await db.incident.update({
    where: { id: incidentId },
    data: {
      engineering_report: engineeringReport as object,
      ...(issueUrl ? { issue_url: issueUrl } : {}),
    },
  });

  // Diagnostic: log what the issue agent actually produced
  const reportTimeline = Array.isArray(engineeringReport.timeline) ? engineeringReport.timeline.length : 0;
  const reportFiles = Array.isArray(engineeringReport.relevant_files) ? engineeringReport.relevant_files.length : 0;
  const reportFuncs = Array.isArray(engineeringReport.relevant_functions) ? engineeringReport.relevant_functions.length : 0;
  const repoFindings = engineeringReport.repository_findings as Record<string, unknown> | null;
  const filesFound = Array.isArray(repoFindings?.files_found) ? (repoFindings!.files_found as string[]).length : 0;
  console.log(
    `[worker] 📋 Report quality: timeline=${reportTimeline} relevant_files=${reportFiles} relevant_functions=${reportFuncs} repo_files_found=${filesFound}${issueUrl ? ` issue=${issueUrl}` : ""}`,
  );
  console.log(`[worker] ✅ issue agent completed for ${incidentId}${issueUrl ? ` — ${issueUrl}` : ""}`);
}

const connection = parseRedisUrl(REDIS_URL);
const worker = new Worker("incident-analysis", processJob, {
  connection,
  concurrency: 1,
  autorun: true,
  lockDuration: 30000,
  stalledInterval: 5000,
});

worker.on("completed", (job) => {
  console.log(`[worker] ✅ Job ${job?.id} completed successfully`);
});

worker.on("failed", (job, err) => {
  console.error(`[worker] ❌ Job ${job?.id} failed:`, err?.message ?? String(err));
});

worker.on("stalled", (jobId) => {
  console.warn(`[worker] ⚠️ Job ${jobId} was stalled (reclaimed by worker)`);
});

async function shutdown() {
  console.log("[worker] shutting down gracefully...");
  await worker.close();
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

console.log("[worker] 🎧 Listening on incident-analysis queue (concurrency=1, stalledCheck=5s)");
