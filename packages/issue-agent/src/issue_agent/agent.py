import json
import logging
import time
from typing import Any
from pydantic_ai import Agent, RunContext, ModelHTTPError

from issue_agent.schemas import IncidentSnapshot, EngineeringReport, TimelineEvent, RepositoryFindings, RepositoryValidation, MissingContext
from issue_agent.evidence import extract_evidence


logger = logging.getLogger(__name__)
_log = logger.getChild("structured")

_MAX_FILE_CHARS = 50000


class IssueAgentDeps:
    def __init__(self, repo: Any):
        self.repo = repo
        self.files_read: list[str] = []
        self.tokens_used: int = 0


def _build_timeline(snapshot: IncidentSnapshot, evidence_list: list) -> list[TimelineEvent]:
    timeline: list[TimelineEvent] = []

    invisible_steps: set[int] = set()
    for si, step in enumerate(snapshot.execution_trace.agent_steps):
        timeline.append(TimelineEvent(
            event_type="execution_step",
            step_index=si,
            description=f"Agent step {step.step_type}",
            source="trace",
        ))
        for tc in step.tool_calls:
            if not tc.success:
                invisible_steps.add(si)
                timeline.append(TimelineEvent(
                    event_type="tool_call",
                    step_index=si,
                    description=f"Tool '{tc.name}' failed: {tc.error or 'unknown error'}",
                    source="trace",
                ))
            else:
                timeline.append(TimelineEvent(
                    event_type="tool_call",
                    step_index=si,
                    description=f"Tool '{tc.name}' succeeded",
                    source="trace",
                ))

    for ei, ev in enumerate(evidence_list):
        timeline.append(TimelineEvent(
            event_type="evidence",
            step_index=min(ev.step_indices) if getattr(ev, "step_indices", None) else None,
            description=f"Evidence: {ev.failure_mode} — {ev.summary[:120]}",
            source="trace",
            evidence_refs=[ei],
        ))

    for fi, fm in enumerate(snapshot.evaluation.failure_modes):
        first_bad = min(invisible_steps) if invisible_steps else None
        timeline.append(TimelineEvent(
            event_type="failure_observable",
            step_index=first_bad,
            description=f"Evaluator detected failure mode: {fm}",
            source="evaluator",
            evidence_refs=[fi],
        ))

    last_failed = max(invisible_steps) if invisible_steps else (len(snapshot.execution_trace.agent_steps) - 1)
    timeline.append(TimelineEvent(
        event_type="root_cause",
        step_index=last_failed,
        description=f"Final failure: {snapshot.evaluation.reasoning[:200]}",
        source="evaluator",
    ))

    return timeline


SYSTEM_PROMPT = """You are a senior engineer investigating an AI system incident.

Your task:
1. Review the incident snapshot (execution traces, evaluator output, telemetry, timeline).
2. Use repository tools to find the relevant code and validate evaluator findings.
3. Search for symbols, filenames, and function names from the trace.
4. Build a code graph around suspected files and traverse it.
5. Read the smallest set of functions needed to understand the bug.
6. Write an engineering report with ALL fields populated.

RULES:

**Timeline Reconstruction**
- The timeline is ordered: execution steps and tool calls first, then evidence, then evaluator findings.
- Identify where the failure first became observable (look for failed tool calls in the timeline).
- Describe how it propagated and explain the final incorrect behavior.
- The engineer reading this should understand "where did the incident begin, and how did it propagate into the final failure?"

**Evidence Grounding**
- For every major conclusion in root_cause, suspected_components, suggested_investigation, and suggested_fix, reference supporting evidence.
- Use evidence_analysis to explain how each conclusion is supported.
- If evidence is insufficient, state "INSUFFICIENT EVIDENCE" and explain what is missing. Do not speculate.

**Repository Validation**
- The input includes "evaluator_suspected_components" — a list of components the evaluator identified.
- You MUST copy these directly into the `suspected_components` output field. This field is REQUIRED and MUST NOT BE EMPTY if evaluator provided components.
- Then validate each one by searching the repository.
- Populate BOTH:
  1. suspected_components — COPY the evaluator_suspected_components list here exactly (from evaluator + any you discover). THIS IS MANDATORY.
  2. repository_findings.validated_components — detailed validation status for each:
     - "confirmed" — found in repository (include found_paths)
     - "suggested" — mentioned by evaluator but not found
     - "not_found" — searched but does not exist in this repo
     - "not_searched" — not attempted
- Also populate repository_findings.files_found, functions_found, and symbols_searched.
- If no relevant implementation can be located, populate missing_context explaining why.

**Hallucination Prevention**
- Never invent repository files, functions, classes, APIs, tools, services, or components.
- Every referenced entity must originate from either: evaluator output OR repository investigation (search_repo, read_file, build_code_graph).
- If no supporting evidence exists, state that the information could not be verified.

**Root Cause Analysis**
- Explain: what failed, why it failed, what evidence supports this conclusion, what system component is responsible, and what secondary effects occurred.
- If multiple contributing factors exist, list them separately in secondary_effects.

**Regression Tests**
- Generate tests that directly validate the identified failure mode.
- Map failure mode to test type:
  - context_overflow -> token budget tests
  - handoff_failure -> context propagation tests
  - looping -> retry limit tests
  - tool_anomaly -> tool failure handling tests
  - hallucination -> grounding verification tests
  - (other failure modes -> appropriate specific test type)
- Avoid generic testing recommendations.

Fill ALL fields of the report:
executive_summary, impact, timeline (analyze the pre-built one), root_cause, evidence_analysis, evidence, suspected_components, repository_findings, missing_context, relevant_files, relevant_functions, suggested_investigation, suggested_fix, suggested_tests, secondary_effects, confidence, issue_title, summary.
"""


def _build_agent() -> Agent:
    agent = Agent(
        model="google:gemini-3.1-flash-lite",
        deps_type=IssueAgentDeps,
        output_type=EngineeringReport,
        system_prompt=SYSTEM_PROMPT,
    )

    @agent.tool
    def search_repo(ctx: RunContext[IssueAgentDeps], query: str) -> str:
        result = ctx.deps.repo.search_symbol(query)
        ctx.deps.tokens_used += 1
        return json.dumps(result, indent=2)

    @agent.tool
    def read_file(ctx: RunContext[IssueAgentDeps], path: str) -> str:
        content = ctx.deps.repo.read_file(path)
        ctx.deps.files_read.append(path)
        ctx.deps.tokens_used += 1
        if content is None:
            return f"File not found: {path}"
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + f"\n<!-- truncated at {_MAX_FILE_CHARS} chars -->"
        return content

    @agent.tool
    def build_code_graph(ctx: RunContext[IssueAgentDeps], file_paths: list[str]) -> str:
        graph = ctx.deps.repo.build_code_graph(file_paths)
        ctx.deps.tokens_used += 1
        return graph.model_dump_json(indent=2)

    return agent


def create_github_issue_from_report(repo: Any, report: EngineeringReport, incident_id: str) -> str | None:
    title = report.issue_title or f"Incident Report: {report.summary[:80]}"
    body_parts = [
        f"## Incident: {incident_id}",
        f"**Confidence:** {report.confidence}",
        f"**Impact:** {report.impact}",
        f"**Summary:** {report.summary}",
        f"**Root Cause:** {report.root_cause}",
    ]
    if report.evidence:
        body_parts.append("### Evidence\n" + "\n".join(f"- {e}" for e in report.evidence))
    if report.suspected_components:
        body_parts.append("### Suspected Components\n" + "\n".join(f"- {c}" for c in report.suspected_components))
    if report.suggested_investigation:
        body_parts.append("### Suggested Investigation\n" + "\n".join(f"- {i}" for i in report.suggested_investigation))
    if report.suggested_fix:
        body_parts.append(f"### Suggested Fix\n{report.suggested_fix}")
    if report.suggested_tests:
        body_parts.append("### Regression Tests\n" + "\n".join(f"- {t}" for t in report.suggested_tests))
    body = "\n\n".join(body_parts)
    return repo.create_issue(title, body)


def run_issue_agent(
    snapshot: IncidentSnapshot,
    repo: Any,
    max_retries: int = 5,
) -> EngineeringReport | None:
    evidence = extract_evidence(snapshot)
    deps = IssueAgentDeps(repo=repo)

    timeline = _build_timeline(snapshot, evidence)

    input_data = {
        "incident_id": snapshot.incident_id,
        "failure_modes": snapshot.evaluation.failure_modes,
        "confidence": snapshot.evaluation.confidence,
        "reasoning": snapshot.evaluation.reasoning,
        "severity": snapshot.evaluation.severity,
        "evidence": [e.model_dump() for e in evidence],
        "timeline": [t.model_dump() for t in timeline],
        "evaluator_suspected_components": snapshot.metadata.get("suspected_components", []),
        "agent_steps": [
            {
                "step_type": s.step_type,
                "planner_output": s.planner_output,
                "tool_calls": [t.model_dump() for t in s.tool_calls],
                "context": s.context,
                "latency_ms": s.latency_ms,
            }
            for s in snapshot.execution_trace.agent_steps
        ],
        "model": snapshot.execution_trace.model,
        "tokens_used": snapshot.execution_trace.tokens_used,
        "total_latency_ms": snapshot.execution_trace.total_latency_ms,
        "telemetry": snapshot.telemetry,
        "metadata": snapshot.metadata,
    }
    input_json = json.dumps(input_data, indent=2)
    input_size = len(input_json)

    agent = _build_agent()

    last_error: Exception | None = None
    start_time = time.monotonic()

    for attempt in range(max_retries):
        _rate_limit_wait()
        try:
            result = agent.run_sync(input_json, deps=deps)
            break
        except ModelHTTPError as e:
            last_error = e
            if e.status_code != 429:
                _log.error("model_http_error", extra={"status": e.status_code, "model": e.model_name})
                return None
            retry_after = _parse_retry_delay(e.body)
            _log.warning(
                "rate_limit_retry",
                extra={"attempt": attempt + 1, "max_retries": max_retries, "retry_after": retry_after},
            )
            if attempt + 1 == max_retries:
                return None
            time.sleep(retry_after)
        except Exception as e:
            last_error = e
            _log.error("unexpected_error", extra={"error": str(e)})
            return None
    else:
        _log.error("max_retries_exceeded", extra={"max_retries": max_retries, "last_error": str(last_error)})
        return None

    elapsed = time.monotonic() - start_time
    usage = result.usage

    _log.info(
        "run_complete",
        extra={
            "run_id": result.run_id,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "requests": usage.requests,
            "tool_calls": usage.tool_calls,
            "latency_s": round(elapsed, 3),
            "input_size_bytes": input_size,
            "retries": attempt,
            "files_read": list(deps.files_read),
            "files_read_count": len(deps.files_read),
            "app_tokens_used": deps.tokens_used,
            "confidence": result.output.confidence,
            "summary": result.output.summary[:120] if result.output.summary else "",
        },
    )

    for msg in result.all_messages():
        for part in getattr(msg, "parts", ()):
            pk = getattr(part, "part_kind", None)
            if pk == "system-prompt":
                _log.info("system_prompt", extra={"content": part.content[:300]})
            elif pk == "user-prompt":
                content = part.content[:300] if isinstance(part.content, str) else str(part.content)[:300]
                _log.info("user_prompt", extra={"content": content})
            elif pk == "text":
                _log.info("model_response", extra={"content": part.content[:500]})
            elif pk == "tool-call":
                _log.info("tool_call", extra={"tool": part.tool_name, "tool_args_count": len(str(part.args))})
            elif pk == "tool-return":
                status = "ok" if getattr(part, "outcome", None) in (None, "success") else "fail"
                _log.info("tool_return", extra={"tool": part.tool_name, "status": status})

    logger.info(
        "Issue agent completed. Tokens: %d, Files read: %d, Confidence: %.2f",
        deps.tokens_used,
        len(deps.files_read),
        result.output.confidence,
    )
    return result.output


_last_request_time: float = 0.0


def _rate_limit_wait(min_interval: float = 5.0):
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_time = time.monotonic()


def _parse_retry_delay(body: object, default: float = 10.0) -> float:
    if isinstance(body, dict):
        for key in ("retryDelay", "retry_delay", "Retry-After"):
            raw = body.get(key) or _deep_get(body, key)
            if raw is not None:
                try:
                    if isinstance(raw, str) and raw.endswith("s"):
                        return float(raw[:-1])
                    return float(raw)
                except (ValueError, TypeError):
                    pass
    return default * 2


def _deep_get(d: dict, key: str) -> object | None:
    if key in d:
        return d[key]
    for v in d.values():
        if isinstance(v, dict):
            result = _deep_get(v, key)
            if result is not None:
                return result
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    result = _deep_get(item, key)
                    if result is not None:
                        return result
    return None