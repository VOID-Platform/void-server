import { execFile } from "child_process";

const PYTHON = process.env.EVALUATOR_PYTHON ?? "python3";
const PYTHONPATH = process.env.EVALUATOR_PYTHONPATH ?? "";
const DEFAULT_MAX_BUFFER = 10485760;
const parsedMaxBuffer = parseInt(process.env.EVALUATOR_MAX_BUFFER ?? "", 10);
const EVALUATOR_MAX_BUFFER =
  Number.isFinite(parsedMaxBuffer) && parsedMaxBuffer > 0
    ? parsedMaxBuffer
    : DEFAULT_MAX_BUFFER;


export function runPythonModule(module: string, inputJson: string, timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      PYTHON,
      ["-m", module],
      {
        env: {
          ...process.env,
          ...(PYTHONPATH ? { PYTHONPATH } : {}),
        },
        maxBuffer: EVALUATOR_MAX_BUFFER,
        timeout: timeoutMs,
      },
      (err, stdout, stderr) => {
        if (err) {
          reject(new Error(`${module} exited: ${err.message}\nStderr: ${stderr}`));
          return;
        }
        resolve(stdout.trim());
      },
    );
    child.stdin?.write(inputJson);
    child.stdin?.end();
  });
}