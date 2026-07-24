import { execFile } from "child_process";

const PYTHON = process.env.EVALUATOR_PYTHON ?? "python3";
const PYTHONPATH = process.env.EVALUATOR_PYTHONPATH ?? "";
const EVALUATOR_MAX_BUFFER = parseInt(process.env.EVALUATOR_MAX_BUFFER ?? "10485760", 10);

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