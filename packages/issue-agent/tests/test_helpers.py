import json
import logging
import os
import sys


_HERE = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))

_log = logging.getLogger("issue_agent")
_log.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("\n[issue-agent] %(levelname)s %(message)s\n"))
_log.addHandler(_handler)
_log.propagate = False

_captured_logs: list[dict] = []


class _LogCapture(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        d = {"level": record.levelname, "msg": record.getMessage()}
        extras = {k: v for k, v in record.__dict__.items() if k not in logging.LogRecord("n", 0, "", 0, "", (), None).__dict__}
        if extras:
            d["extra"] = extras
        _captured_logs.append(d)


_capture_handler = _LogCapture()
_capture_handler.setLevel(logging.DEBUG)
_log.addHandler(_capture_handler)


_SEVERITY_MAP = {"P0": "CRITICAL", "P1": "HIGH", "P2": "MEDIUM", "DEFER": "LOW"}

def _extract_severity(eval_data: dict) -> str:
    raw = eval_data.get("severity", eval_data.get("urgency_tier", eval_data.get("urgency", "MEDIUM")))
    if isinstance(raw, dict):
        raw = raw.get("tier", str(raw.get("status", "MEDIUM")))
    mapped = _SEVERITY_MAP.get(raw)
    if mapped:
        return mapped
    if isinstance(raw, str) and raw in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        return raw
    return "MEDIUM"


def _load_dotenv():
    dotenv = os.path.join(_PROJECT_ROOT, ".env")
    if not os.path.exists(dotenv):
        return
    with open(dotenv) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = val


_load_dotenv()
EVALUATOR_SRC = os.path.join(_PROJECT_ROOT, "packages", "evaluator", "src")
ISSUE_AGENT_SRC = os.path.join(_PROJECT_ROOT, "packages", "issue-agent", "src")

if EVALUATOR_SRC not in sys.path:
    sys.path.insert(0, EVALUATOR_SRC)
if ISSUE_AGENT_SRC not in sys.path:
    sys.path.insert(0, ISSUE_AGENT_SRC)


from issue_agent.schemas import IncidentSnapshot, ExecutionTrace, AgentStep, ToolCall, EvaluationResult
from issue_agent.agent import run_issue_agent
from issue_agent.repository import LocalRepo


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def run_evaluator(incident: dict) -> dict:
    from evaluator.agent import Agent as EvaluatorAgent
    agent = EvaluatorAgent()
    result = agent.evaluate(incident)
    if result is None:
        return {"evaluation": {}, "metadata": {}}
    return json.loads(result.model_dump_json())


def build_snapshot(incident: dict, evaluator: dict) -> IncidentSnapshot:
    eval_data = evaluator.get("evaluation", {})
    failure_modes = eval_data.get("failure_modes", [])
    if not failure_modes:
        failure_modes = incident.get("latest_labels", ["NONE_DETECTED"])

    steps = []
    for s in incident.get("agent_steps", []):
        llm = s.get("llm_response", {})
        tool_calls = [
            ToolCall(
                name=tc.get("name", ""),
                input=tc.get("input", ""),
                output=tc.get("output"),
                latency_ms=tc.get("latency_ms"),
                success=tc.get("success", True),
                error=tc.get("error"),
            )
            for tc in s.get("tool_calls", [])
        ]
        steps.append(AgentStep(
            step_type=str(s.get("step_number", "")),
            planner_output=llm.get("response", ""),
            tool_calls=tool_calls,
            context="",
            latency_ms=s.get("latency_ms"),
        ))

    telemetry = incident.get("telemetry", {})

    # Derive model from the incident trace if available
    traced_model = incident.get("model")
    if not traced_model:
        # Fallback: try to get from first step's llm_response
        for s in incident.get("agent_steps", []):
            llm = s.get("llm_response", {})
            if isinstance(llm.get("model"), str):
                traced_model = llm["model"]
                break
    model_name = traced_model or "gemini-3.1-flash-lite"

    return IncidentSnapshot(
        incident_id=incident.get("id", incident.get("execution_id", "unknown")),
        execution_trace=ExecutionTrace(
            agent_steps=steps,
            model=model_name,
            total_latency_ms=telemetry.get("total_latency_ms"),
            tokens_used=telemetry.get("total_prompt_tokens", 0) or 0,
        ),
        evaluation=EvaluationResult(
            failure_modes=failure_modes,
            confidence=eval_data.get("confidence", 0.5),
            reasoning=eval_data.get("suspected_root_cause", eval_data.get("summary", "")),
            severity=_extract_severity(eval_data),
        ),
        telemetry=telemetry,
        metadata={
            "classification": eval_data.get("classification", ""),
            "summary": eval_data.get("summary", ""),
            "suspected_components": eval_data.get("suspected_components", []),
            "recommendations": eval_data.get("recommendations", []),
        },
    )


def validate_report(report, expected: dict) -> list[str]:
    errors = []
    classification = expected.get("classification", "")

    if classification == "INSUFFICIENT_EVIDENCE":
        if expected.get("must_not_suggest_fix"):
            fix = (report.suggested_fix or "").strip()
            if fix and fix not in ("No fix required.", "INSUFFICIENT EVIDENCE"):
                errors.append(f"Expected no suggested fix, got: {fix[:60]}")
        if expected.get("must_not_identify_root_cause"):
            rc = (report.root_cause or "").strip()
            allowed_boilerplate = {"INSUFFICIENT EVIDENCE", "Unknown.", "missing trace data", "cannot investigate", "insufficient evidence"}
            if rc and rc not in allowed_boilerplate:
                errors.append(f"Expected no specific root cause, got: {rc[:60]}")
        max_conf = expected.get("confidence_max", 1.0)
        if report.confidence > max_conf:
            errors.append(f"Confidence {report.confidence} > max {max_conf}")
        summary = (report.summary or "").lower()
        for kw in expected.get("summary_must_contain", []):
            if kw not in summary:
                errors.append(f"Summary should contain '{kw}'")

    if classification == "REAL_INCIDENT":
        rc = (report.root_cause or "").lower()
        for kw in expected.get("root_cause_must_contain", []):
            if kw not in rc:
                errors.append(f"Root cause should contain '{kw}'")
        comps = " ".join(report.suspected_components or [])
        for kw in expected.get("suspected_components_must_contain", []):
            if kw.lower() not in comps.lower():
                errors.append(f"Components should contain '{kw}'")
        inv = " ".join(report.suggested_investigation or [])
        for kw in expected.get("suggested_investigation_must_contain", []):
            if kw.lower() not in inv.lower():
                errors.append(f"Investigation should contain '{kw}'")
        tests = " ".join(report.suggested_tests or [])
        for kw in expected.get("suggested_tests_must_contain", []):
            if kw.lower() not in tests.lower():
                errors.append(f"Tests should contain '{kw}'")
        # New assertions
        ev = " ".join(report.evidence or [])
        for kw in expected.get("evidence_must_contain", []):
            if kw.lower() not in ev.lower():
                errors.append(f"Evidence should contain '{kw}'")
        rel_files = " ".join(report.relevant_files or [])
        for kw in expected.get("relevant_files_must_contain", []):
            if kw.lower() not in rel_files.lower():
                errors.append(f"Relevant files should contain '{kw}'")
        if report.confidence < expected.get("confidence_min", 0.0):
            errors.append(f"Confidence {report.confidence} < min {expected['confidence_min']}")
        if not (report.summary or "").strip():
            errors.append("REAL_INCIDENT must have a summary")
        if not (report.root_cause or "").strip():
            errors.append("REAL_INCIDENT must have a root cause")
        if not report.evidence:
            errors.append("REAL_INCIDENT must have evidence")

    return errors


def run_scenario(scenario: str) -> dict:
    incident_path = os.path.join(_PROJECT_ROOT, "evaluation_dataset", "incidents", scenario, "incident.json")
    scenario_dir = os.path.join(_HERE, "issue-agent", scenario)
    eval_path = os.path.join(scenario_dir, "evaluation.json")
    expected_path = os.path.join(scenario_dir, "expected.json")

    incident = load_json(incident_path)
    has_api = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    if has_api and os.path.exists(eval_path):
        evaluator_output = load_json(eval_path)
    elif has_api:
        evaluator_output = run_evaluator(incident)
        os.makedirs(scenario_dir, exist_ok=True)
        with open(eval_path, "w") as f:
            json.dump(evaluator_output, f, indent=2)
    else:
        evaluator_output = {"evaluation": {}, "metadata": {}}

    snapshot = build_snapshot(incident, evaluator_output)
    expected = load_json(expected_path)

    _captured_logs.clear()

    repo = LocalRepo(os.path.join(_PROJECT_ROOT, "evaluation_dataset", "incidents", scenario))
    report = run_issue_agent(snapshot, repo)

    logs = list(_captured_logs)

    if report is None:
        return {"scenario": scenario, "passed": False, "errors": ["Issue agent returned None"], "logs": logs}

    errors = validate_report(report, expected)
    return {"scenario": scenario, "passed": len(errors) == 0, "errors": errors, "logs": logs}


SCENARIOS = [
    "context-overflow", "handoff-failure", "looping", "silent-hallucination", "tool-anomaly",
    "crash-loop", "critical-escalation", "example", "false-positive", "insufficient-evidence",
    "mixed-labels", "rate-limit", "recurring", "transient-error",
]