import { Worker, Job } from "bullmq";
import { execFile } from "child_process";
import { db } from "./db";

const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379";

function parseRedisUrl(urlStr: string) {
  const parsed = new URL(urlStr);
  return {
    host: parsed.hostname,
    port: parsed.port ? parseInt(parsed.port, 10) : 6379,
    ...(parsed.password ? { password: decodeURIComponent(parsed.password) } : {}),
  };
}

function runEvaluator(incidentJson: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      "python3",
      ["-m", "evaluator"],
      {
        env: { ...process.env, PYTHONPATH: process.env.PYTHONPATH ?? "" },
        maxBuffer: 1024 * 1024,
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

  const raw = await runEvaluator(JSON.stringify(incident));
  const parsed = JSON.parse(raw);

  if (parsed.error) {
    await db.incident.update({
      where: { id: incidentId },
      data: { analysis_status: "FAILED" },
    });
    console.error(`[worker] evaluator failed for ${incidentId}: ${parsed.error}`);
    return;
  }

  const evaluation = parsed.evaluation;
  const metadata = parsed.metadata;

  const report = await db.report.create({
    data: {
      incident_id: incidentId,
      model: metadata.model_version,
      report: parsed,
    },
  });

  await db.incident.update({
    where: { id: incidentId },
    data: {
      analysis_status: "COMPLETED",
      confidence: evaluation.confidence,
      latest_report_id: report.id,
    },
  });

  console.log(
    `[worker] completed ${incidentId}: ${evaluation.classification} (confidence: ${evaluation.confidence})`,
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

console.log("[worker] listening on incident-analysis queue");
