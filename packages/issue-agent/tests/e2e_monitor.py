#!/usr/bin/env python3
"""E2E monitoring script — runs all scenarios and prints a full report.
Not a test. Logs LLM responses, tool calls, retries, tokens, latency, final report."""

import json
import logging
import os
import sys
import time

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "evaluator", "src"))

from issue_agent.agent import run_issue_agent
from issue_agent.repository import LocalRepo
from issue_agent.schemas import EngineeringReport

# ── logging setup: capture structured logs with extra fields ──────────────
_log = logging.getLogger("issue_agent")
_log.setLevel(logging.DEBUG)

captured: list[dict] = []


class CaptureHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in logging.LogRecord("n", 0, "", 0, "", (), None).__dict__
        }
        captured.append({"level": record.levelname, "msg": record.getMessage(), "extra": extras})


_log.handlers.clear()
_log.addHandler(CaptureHandler())

# silence noisy libs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ── helpers ───────────────────────────────────────────────────────────────

_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
SCENARIOS = [
    "context-overflow", "handoff-failure", "looping", "silent-hallucination", "tool-anomaly",
    "crash-loop", "critical-escalation", "example", "false-positive", "insufficient-evidence",
    "mixed-labels", "rate-limit", "recurring", "transient-error",
]


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


def build_snapshot(incident: dict, evaluator: dict):
    from issue_agent.schemas import IncidentSnapshot, ExecutionTrace, AgentStep, ToolCall, EvaluationResult
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
            latency_ms=s.get("telemetry", {}).get("latency_ms") if isinstance(s.get("telemetry"), dict) else None,
        ))
    telemetry = incident.get("telemetry", {})
    return IncidentSnapshot(
        incident_id=incident.get("id", incident.get("execution_id", "unknown")),
        execution_trace=ExecutionTrace(
            agent_steps=steps,
            model="gemini-3.1-flash-lite",
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

# ── report printing ───────────────────────────────────────────────────────

SEP = "=" * 72
SUB = "-" * 72


def print_report(scenario: str) -> dict:
    incident_path = os.path.join(_PROJECT_ROOT, "evaluation_dataset", "incidents", scenario, "incident.json")
    scenario_dir = os.path.join(_HERE, "issue-agent", scenario)
    eval_path = os.path.join(scenario_dir, "evaluation.json")

    incident = load_json(incident_path)

    # ── evaluator ──────────────────────────────────────────────────────
    has_api = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if has_api and os.path.exists(eval_path):
        evaluator_output = load_json(eval_path)
    elif has_api:
        print("  [running evaluator...]")
        evaluator_output = run_evaluator(incident)
        os.makedirs(scenario_dir, exist_ok=True)
        with open(eval_path, "w") as f:
            json.dump(evaluator_output, f, indent=2)
    else:
        evaluator_output = {"evaluation": {}, "metadata": {}}

    eval_data = evaluator_output.get("evaluation", {})
    print(f"\n{SEP}")
    print(f"  SCENARIO: {scenario}")
    print(f"  ID:       {incident.get('id', incident.get('execution_id', '?'))}")
    print(f"{SEP}")

    print(f"\n  ── EVALUATOR OUTPUT ──")
    print(f"  Classification: {eval_data.get('classification', '?')}")
    print(f"  Confidence:     {eval_data.get('confidence', '?')}")
    print(f"  Failure modes:  {', '.join(eval_data.get('failure_modes', []))}")
    print(f"  Severity:       {_extract_severity(eval_data)}")
    print(f"\n  Summary:")
    for line in eval_data.get("summary", "").split(". "):
        print(f"    • {line.strip()}.")
    print(f"\n  Suspected root cause:")
    for line in eval_data.get("suspected_root_cause", "").split(". "):
        print(f"    • {line.strip()}.")
    print(f"\n  Suspected components: {', '.join(eval_data.get('suspected_components', []))}")
    print(f"\n  Reasoning:")
    for r in eval_data.get("reasoning", []):
        print(f"    • {r}")
    print(f"\n  Recommendations:")
    for r in eval_data.get("recommendations", []):
        print(f"    • {r}")

    # ── issue agent ────────────────────────────────────────────────────
    snapshot = build_snapshot(incident, evaluator_output)
    repo = LocalRepo(os.path.join(_PROJECT_ROOT, "evaluation_dataset", "incidents", scenario))

    captured.clear()
    t0 = time.monotonic()
    report: EngineeringReport | None = run_issue_agent(snapshot, repo, max_retries=5)
    wall = time.monotonic() - t0
    logs = list(captured)

    # ── agent logs ─────────────────────────────────────────────────────
    print(f"\n  ── ISSUE AGENT LOGS ──")

    retry_events = [l for l in logs if l.get("msg") == "rate_limit_retry"]
    if retry_events:
        print(f"  ⚠  RETRIES: {len(retry_events)}")
        for r in retry_events:
            e = r["extra"]
            print(f"     attempt {e.get('attempt', '?')}/{e.get('max_retries', '?')} retry_after={e.get('retry_after', '?')}s")

    error_events = [l for l in logs if l["level"] == "ERROR"]
    if error_events:
        print(f"  ✖ ERRORS:")
        for e in error_events:
            print(f"     {e['msg']}: {e['extra']}")

    # full LLM conversation
    print("\n  ── LLM CONVERSATION ──")
    for log_entry in logs:
        msg = log_entry["msg"]
        ex = log_entry["extra"]
        if msg == "system_prompt":
            print(f"\n  [SYSTEM PROMPT]\n{_indent(ex.get('content', ''), 4)}")
        elif msg == "user_prompt":
            print(f"\n  [USER PROMPT]\n{_indent(ex.get('content', ''), 4)}")
        elif msg == "model_response":
            print(f"\n  ── MODEL RESPONSE ──\n{_indent(ex.get('content', ''), 4)}")
        elif msg == "tool_call":
            print(f"\n  ── TOOL CALL: {ex.get('tool', '?')} ──")
            count = ex.get("tool_args_count")
            if count is not None:
                print(f"  (args: {count} chars)")
        elif msg == "tool_return":
            status = ex.get("status", "?")
            mark = "✓" if status == "ok" else "✗"
            print(f"  {mark} TOOL RETURN: {ex.get('tool', '?')} [{status}]")
        elif msg == "run_complete":
            print(f"\n  ── RUN METRICS ──")
            print(f"     run_id:       {ex.get('run_id', '?')}")
            print(f"     input_tokens: {ex.get('input_tokens', '?')}")
            print(f"     output_tokens:{ex.get('output_tokens', '?')}")
            print(f"     total_tokens: {ex.get('total_tokens', '?')}")
            print(f"     requests:     {ex.get('requests', '?')}")
            print(f"     tool_calls:   {ex.get('tool_calls', '?')}")
            print(f"     latency:      {ex.get('latency_s', '?')}s")
            print(f"     retries:      {ex.get('retries', '?')}")
            print(f"     files_read:   {ex.get('files_read_count', 0)} {ex.get('files_read', [])}")
            print(f"     app_tokens:   {ex.get('app_tokens_used', 0)}")
            print(f"     confidence:   {ex.get('confidence', '?')}")
            print(f"     summary:      {ex.get('summary', '')}")

    # ── final report ───────────────────────────────────────────────────
    print("\n  ── ENGINEERING REPORT ──")
    if report is None:
        print("  ✖ Agent returned None (failed/rate-limited)")
    else:
        print(f"  Issue Title:  {report.issue_title or '(not set)'}")
        print(f"  Confidence:   {report.confidence}")
        print(f"\n  Executive Summary: {report.executive_summary or report.summary}")
        if report.impact:
            print(f"\n  Impact: {report.impact}")
        print(f"\n  ── Timeline ──")
        if report.timeline:
            for ev in report.timeline:
                badge = {
                    "execution_step": "▶",
                    "tool_call": "⚙",
                    "failure_observable": "✖",
                    "evidence": "◈",
                    "root_cause": "◆",
                }.get(ev.event_type, "•")
                step = f" step#{ev.step_index}" if ev.step_index is not None else ""
                refs = f" [evidence: {ev.evidence_refs}]" if ev.evidence_refs else ""
                print(f"    {badge} [{ev.source}]{step} {ev.description}{refs}")
        else:
            print("    (timeline not populated by agent)")
        print(f"\n  ── Root Cause ──")
        print(f"  {report.root_cause}")
        if report.secondary_effects:
            print(f"\n  Secondary Effects:")
            for s in report.secondary_effects:
                print(f"    • {s}")
        print(f"\n  ── Evidence Analysis ──")
        print(f"  {report.evidence_analysis or '(not provided)'}")
        print(f"\n  Evidence:")
        for e in report.evidence:
            print(f"    • {e}")
        print(f"\n  Suspected Components: {', '.join(report.suspected_components)}")
        print(f"\n  ── Repository Findings ──")
        rf = report.repository_findings
        if rf.validated_components:
            print(f"  Validated Components:")
            for vc in rf.validated_components:
                paths = ", ".join(vc.found_paths) if vc.found_paths else ""
                notes = f" — {vc.notes}" if vc.notes else ""
                print(f"    [{vc.status:12s}] {vc.component}{'  ' + paths if paths else ''}{notes}")
        else:
            print(f"  (no components validated)")
        if rf.files_found:
            print(f"  Files Found: {', '.join(rf.files_found)}")
        if rf.functions_found:
            print(f"  Functions Found: {', '.join(rf.functions_found)}")
        if rf.symbols_searched:
            print(f"  Symbols Searched: {', '.join(rf.symbols_searched)}")
        if rf.missing_context_reason:
            print(f"  Missing Context: {rf.missing_context_reason}")
        if report.missing_context:
            print(f"\n  ── Missing Context ──")
            print(f"  Reason: {report.missing_context.reason}")
            if report.missing_context.missing_information:
                print(f"  Missing Information:")
                for m in report.missing_context.missing_information:
                    print(f"    • {m}")
            if report.missing_context.recommendations:
                print(f"  Recommendations:")
                for r in report.missing_context.recommendations:
                    print(f"    • {r}")
        print(f"\n  Relevant Files: {', '.join(report.relevant_files) if report.relevant_files else '(none)'}")
        print(f"\n  Relevant Functions: {', '.join(report.relevant_functions) if report.relevant_functions else '(none)'}")
        print(f"\n  Suggested Investigation:")
        for i in report.suggested_investigation:
            print(f"    • {i}")
        print(f"\n  Suggested Fix: {report.suggested_fix}")
        print(f"\n  Suggested Tests:")
        for t in report.suggested_tests:
            print(f"    • {t}")

    print(f"\n  ── WALL CLOCK: {wall:.2f}s ──")

    return {"scenario": scenario, "logs": logs, "report": report}


def _indent(text: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.split("\n"))


# ── main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else SCENARIOS

    summary: list[dict] = []
    for s in targets:
        r = print_report(s)
        summary.append(r)

    print(f"\n{SEP}")
    print(f"  SUMMARY ({len(summary)} scenarios)")
    print(f"{SEP}")
    for r in summary:
        ok = "✓" if r["report"] is not None else "✗"
        if r["report"]:
            conf = r["report"].confidence
            print(f"  {ok} {r['scenario']:30s}  conf={conf:.2f}")
        else:
            print(f"  {ok} {r['scenario']:30s}  FAILED (no report)")