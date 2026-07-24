import { execFile } from "child_process";

const PYTHON = process.env.EVALUATOR_PYTHON ?? "python3";
const PYTHONPATH = process.env.EVALUATOR_PYTHONPATH ?? "";

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
        maxBuffer: 1024 * 1024,
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