import json
import logging
import time
from typing import Any
from pydantic_ai import Agent, RunContext, ModelHTTPError

from issue_agent.schemas import (
    IncidentSnapshot, EngineeringReport, TimelineEvent,
    RepositoryFindings, RepositoryValidation, MissingContext
)
from issue_agent.evidence import extract_evidence


logger = logging.getLogger(__name__)
_log = logger.getChild("structured")

_MAX_FILE_CHARS = 50000


class IssueAgentDeps:
    def __init__(self, repo: Any):
        self.repo = repo
        self.files_read: list[str] = []
        self.symbols_searched: list[str] = []
        self.tool_calls_used: int = 0


def _build_timeline(snapshot: IncidentSnapshot, evidence_list: list) -> list[TimelineEvent]:
    """Construct a structured execution timeline from the trace and evaluator findings."""
    timeline: list[TimelineEvent] = []
    invisible_steps: set[int] = set()

    for si, step in enumerate(snapshot.execution_trace.agent_steps):
        step_desc = step.step_type
        if step.planner_output:
            step_desc += f" — {step.planner_output[:100]}"
        timeline.append(TimelineEvent(
            event_type="execution_step",
            step_index=si,
            description=f"Agent step {step_desc}",
            source="trace",
        ))
        for tc in step.tool_calls:
            if not tc.success:
                invisible_steps.add(si)
                err_detail = tc.error or "unknown error"
                desc = f"Tool '{tc.name}' FAILED: {err_detail}"
                if tc.latency_ms:
                    desc += f" ({tc.latency_ms:.0f}ms)"
                timeline.append(TimelineEvent(
                    event_type="tool_call",
                    step_index=si,
                    description=desc,
                    source="trace",
                ))
            else:
                desc = f"Tool '{tc.name}' succeeded"
                if tc.latency_ms:
                    desc += f" ({tc.latency_ms:.0f}ms)"
                if tc.output:
                    desc += f" -> {tc.output[:80]}"
                timeline.append(TimelineEvent(
                    event_type="tool_call",
                    step_index=si,
                    description=desc,
                    source="trace",
                ))

    for ei, ev in enumerate(evidence_list):
        timeline.append(TimelineEvent(
            event_type="evidence",
            step_index=min(ev.step_indices) if getattr(ev, "step_indices", None) else None,
            description=f"Evidence [{ev.failure_mode}]: {ev.summary[:120]}",
            source="trace",
            evidence_refs=[ei],
        ))

    for fi, fm in enumerate(snapshot.evaluation.failure_modes):
        first_bad = min(invisible_steps) if invisible_steps else None
        timeline.append(TimelineEvent(
            event_type="failure_observable",
            step_index=first_bad,
            description=f"Evaluator detected failure: {fm}",
            source="evaluator",
            evidence_refs=[fi],
        ))

    last_failed = max(invisible_steps) if invisible_steps else max(len(snapshot.execution_trace.agent_steps) - 1, 0)
    timeline.append(TimelineEvent(
        event_type="root_cause",
        step_index=last_failed,
        description=f"Root cause: {snapshot.evaluation.reasoning[:200]}",
        source="evaluator",
    ))

    return timeline


SYSTEM_PROMPT = """You are a senior software engineer performing an incident investigation for VOID, an AI agent debugging platform.

## Your Mission

Produce an engineering report that a developer can immediately use to find and fix the bug.
The report must answer: "What happened? Where in the code? Which files? Which functions? Why?"

A report with empty `relevant_files`, `relevant_functions`, or `repository_findings` is a FAILURE.

---

## MANDATORY Investigation Protocol

You MUST follow these steps IN ORDER. Do not skip any step.

### Phase 1 — Understand the Incident

Read the input carefully:
- `failure_modes`: what type of failure was detected
- `reasoning`: the evaluator's assessment
- `agent_steps`: the tool calls the failing agent made (names, inputs, errors, latency)
- `timeline`: the ordered execution sequence already built from the trace
- `evaluator_suspected_components`: components the evaluator identified — your MANDATORY starting point for repo search
- `trace_tool_names`: every tool name the agent called — you MUST search for each one

### Phase 2 — Mandatory Repository Investigation

You MUST call `search_repo` for EVERY item in this list. No exceptions:

1. Every name in `trace_tool_names` (e.g. if trace shows `weather.getForecast`, search "getForecast", "weather")
2. Every component in `evaluator_suspected_components`
3. Failure mode keywords:
   - HALLUCINATION -> search "hallucination", "verify", "grounding", "tool_use"
   - TOOL_CALL_ANOMALY -> search "tool_call", "tool_selector", "dispatch"
   - LOOPING -> search "retry", "loop", "iteration"
   - HANDOFF_FAILURE -> search "handoff", "context", "state"
   - SILENT_CONTEXT_OVERFLOW -> search "token", "context_window", "truncat"
4. Any function names or error strings visible in the agent_steps

After each `search_repo` call, read the 2-4 most relevant files with `read_file`.
Then call `build_code_graph` on those files to understand their dependencies.

You MUST populate these fields. Leaving them empty is unacceptable:
- `relevant_files`: file paths you actually called read_file on
- `relevant_functions`: function/class names found in those files that are relevant to the failure
- `repository_findings.files_found`: same as relevant_files
- `repository_findings.functions_found`: same as relevant_functions  
- `repository_findings.symbols_searched`: every query string you passed to search_repo
- `repository_findings.validated_components`: for each evaluator_suspected_component, mark as:
  - "confirmed" if found in the repo (include found_paths)
  - "not_found" if you searched but did not find it
  Never use "not_searched"

### Phase 3 — Write the Engineering Report

**`timeline`** — NEVER leave empty. The input includes a pre-built timeline. Use it verbatim or expand it. Describe what happened chronologically. If there were no agent steps, write at minimum one event explaining the evaluator finding.

**`root_cause`** — Cite specific files and functions. Example:
"dashboard.update() in apps/dashboard/update.ts calls executeQuery() in packages/db/connection.ts. The pooled connection times out after 5 seconds with no retry policy in this execution path, causing the agent to terminate without producing a final response."

**`relevant_files`** — List every file path you called read_file on. If the repo search returned no results, write ["NOT_FOUND — no matching files for: <your search queries>"].

**`relevant_functions`** — List every function/class name from those files that is relevant to the failure.

**`suggested_fix`** — Reference specific file paths and function signatures from your investigation. No generic advice.

**`suggested_tests`** — Write specific test descriptions matching the failure mode and actual code paths found.

**`executive_summary`** — One paragraph. What failed, where, what should the engineer look at first.

---

## Hallucination Prevention

- NEVER invent file paths, function names, class names, or tool names
- Every entity in `relevant_files` must come from an actual `read_file` call that returned content
- Every entity in `relevant_functions` must come from content you actually read
- If a component is not found in the repo, write that explicitly in `missing_context`
- Uncertainty is fine. Invention is not.

---

## Output

Fill ALL fields of EngineeringReport:
executive_summary, impact, timeline, root_cause, evidence_analysis, evidence,
suspected_components, relevant_files, relevant_functions, repository_findings,
missing_context, suggested_investigation, suggested_fix, suggested_tests,
secondary_effects, confidence, issue_title, summary
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
        """Search the repository for files matching a symbol, function, or filename.

        CALL THIS for every tool name, component, and failure mode keyword.

        Args:
            query: Symbol, function name, filename pattern, or keyword to search for.

        Returns:
            JSON object with 'matches' list, each having 'path' and 'matched_in'.
        """
        logger.info("[repo] search_repo query=%r", query)
        result = ctx.deps.repo.search_symbol(query)
        ctx.deps.symbols_searched.append(query)
        ctx.deps.tool_calls_used += 1
        match_count = len(result.get("matches", []))
        logger.info("[repo] search_repo query=%r -> %d matches", query, match_count)
        return json.dumps(result, indent=2)

    @agent.tool
    def read_file(ctx: RunContext[IssueAgentDeps], path: str) -> str:
        """Read a file from the repository.

        CALL THIS for the 2-4 most relevant files found via search_repo.

        Args:
            path: Repository-relative file path to read.

        Returns:
            File content (truncated at 50KB) or error message.
        """
        logger.info("[repo] read_file path=%r", path)
        content = ctx.deps.repo.read_file(path)
        ctx.deps.tool_calls_used += 1
        if content is None:
            logger.warning("[repo] read_file NOT FOUND path=%r", path)
            return f"File not found: {path}"
        ctx.deps.files_read.append(path)
        logger.info("[repo] read_file path=%r size=%d chars", path, len(content))
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + f"\n<!-- truncated at {_MAX_FILE_CHARS} chars -->"
        return content

    @agent.tool
    def build_code_graph(ctx: RunContext[IssueAgentDeps], file_paths: list[str]) -> str:
        """Build an import/call dependency graph for the given files.

        CALL THIS after reading files to understand how they connect.

        Args:
            file_paths: List of repository-relative file paths to analyze.

        Returns:
            JSON-serialized CodeGraph with nodes (files/functions/classes) and edges (imports/calls).
        """
        logger.info("[repo] build_code_graph files=%s", file_paths)
        graph = ctx.deps.repo.build_code_graph(file_paths)
        ctx.deps.tool_calls_used += 1
        logger.info("[repo] build_code_graph nodes=%d edges=%d", len(graph.nodes), len(graph.edges))
        return graph.model_dump_json(indent=2)

    return agent


def create_github_issue_from_report(repo: Any, report: EngineeringReport, incident_id: str, metadata: dict | None = None) -> str | None:
    title = report.issue_title or f"Incident Report: {report.summary[:80]}"
    metadata = metadata or {}

    body_parts = [
        f"## Incident: {incident_id}",
        "",
        f"**Confidence:** {report.confidence:.0%}",
        f"**Impact:** {report.impact}",
    ]

    # SigNoz trace link — embed directly so engineers can jump to the trace in one click
    trace_id = metadata.get("trace_id", "")
    signoz_url = metadata.get("signoz_trace_url", "")
    if signoz_url and trace_id:
        body_parts.append(f"**Trace:** [{trace_id}]({signoz_url})")
    elif trace_id:
        body_parts.append(f"**Trace ID:** `{trace_id}`")

    body_parts += [
        "",
        "### Executive Summary",
        report.executive_summary or report.summary,
    ]


    # Timeline
    if report.timeline:
        body_parts.append("\n### Execution Timeline")
        icons = {
            "execution_step": "▶",
            "tool_call": "  🔧",
            "evidence": "  📋",
            "failure_observable": "  ⚠️",
            "root_cause": "  💥",
        }
        for event in report.timeline:
            prefix = icons.get(event.event_type, "  •")
            step_ref = f" (step {event.step_index})" if event.step_index is not None else ""
            body_parts.append(f"{prefix} {event.description}{step_ref}")

    # Root cause
    body_parts.append(f"\n### Root Cause\n{report.root_cause}")

    # Evidence analysis
    if report.evidence_analysis:
        body_parts.append(f"\n### Evidence Analysis\n{report.evidence_analysis}")

    # Repository Intelligence
    if report.relevant_files or report.relevant_functions:
        repo_lines = ["\n### Repository Intelligence"]
        if report.relevant_files:
            repo_lines.append("**Relevant Files**")
            for f in report.relevant_files:
                repo_lines.append(f"- `{f}`")
        if report.relevant_functions:
            repo_lines.append("\n**Relevant Functions**")
            for fn in report.relevant_functions:
                repo_lines.append(f"- `{fn}()`")
        body_parts.append("\n".join(repo_lines))

    # Repository findings
    rf = report.repository_findings
    if rf and (rf.validated_components or rf.files_found or rf.symbols_searched):
        findings_lines = ["\n### Repository Findings"]
        if rf.validated_components:
            findings_lines.append("**Validated Components**")
            status_icons = {"confirmed": "✅", "suggested": "💡", "not_found": "❌", "not_searched": "⬜"}
            for vc in rf.validated_components:
                icon = status_icons.get(vc.status, "•")
                line = f"{icon} `{vc.component}` ({vc.status})"
                if vc.found_paths:
                    line += ": " + ", ".join(f"`{p}`" for p in vc.found_paths)
                if vc.notes:
                    line += f" — {vc.notes}"
                findings_lines.append(line)
        if rf.symbols_searched:
            findings_lines.append(f"\n**Symbols Searched:** {', '.join(f'`{s}`' for s in rf.symbols_searched[:10])}")
        body_parts.append("\n".join(findings_lines))

    if report.evidence:
        body_parts.append("### Trace Evidence\n" + "\n".join(f"- {e}" for e in report.evidence))

    if report.suspected_components:
        body_parts.append("### Suspected Components\n" + "\n".join(f"- `{c}`" for c in report.suspected_components))

    if report.secondary_effects:
        body_parts.append("### Secondary Effects\n" + "\n".join(f"- {e}" for e in report.secondary_effects))

    if report.suggested_investigation:
        body_parts.append("### Suggested Investigation\n" + "\n".join(f"- {i}" for i in report.suggested_investigation))

    if report.suggested_fix:
        body_parts.append(f"### Suggested Fix\n{report.suggested_fix}")

    if report.suggested_tests:
        body_parts.append("### Regression Tests\n" + "\n".join(f"- {t}" for t in report.suggested_tests))

    if report.missing_context:
        mc = report.missing_context
        mc_lines = [f"### Missing Context\n**Reason:** {mc.reason}"]
        if mc.missing_information:
            mc_lines.append("**Missing:** " + "; ".join(mc.missing_information))
        if mc.recommendations:
            mc_lines.append("**Recommendations:** " + "; ".join(mc.recommendations))
        body_parts.append("\n".join(mc_lines))

    body_parts.append("\n---\n*Generated by VOID Issue Agent*")
    body = "\n\n".join(body_parts)
    return repo.create_issue(title, body)


def run_issue_agent(
    snapshot: IncidentSnapshot,
    repo: Any,
    max_retries: int = 5,
) -> EngineeringReport | None:
    evidence = extract_evidence(snapshot)
    deps = IssueAgentDeps(repo=repo)

    # Build timeline once in Python — guaranteed populated from trace data
    pre_built_timeline = _build_timeline(snapshot, evidence)

    # Collect trace tool names for input and diagnostics
    trace_tool_names = list({
        tc.name
        for step in snapshot.execution_trace.agent_steps
        for tc in step.tool_calls
    })

    logger.info(
        "[issue-agent] starting: incident=%s failure_modes=%s trace_steps=%d trace_tools=%s suspected=%s",
        snapshot.incident_id,
        snapshot.evaluation.failure_modes,
        len(snapshot.execution_trace.agent_steps),
        trace_tool_names,
        snapshot.metadata.get("suspected_components", []),
    )

    input_data = {
        "incident_id": snapshot.incident_id,
        "incident_title": snapshot.metadata.get("incident_title", ""),
        "failure_modes": snapshot.evaluation.failure_modes,
        "confidence": snapshot.evaluation.confidence,
        "reasoning": snapshot.evaluation.reasoning,
        "severity": snapshot.evaluation.severity,
        "evidence": [e.model_dump() for e in evidence],
        # Pre-built timeline passed as context for the LLM
        "timeline": [t.model_dump() for t in pre_built_timeline],
        # Evaluator components — LLM MUST search each one
        "evaluator_suspected_components": snapshot.metadata.get("suspected_components", []),
        "evaluator_suspected_root_cause": snapshot.metadata.get("suspected_root_cause", ""),
        # Tool names from trace — LLM MUST search each one
        "trace_tool_names": trace_tool_names,
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

    logger.info("[issue-agent] input_size=%d bytes pre_built_timeline=%d events", input_size, len(pre_built_timeline))

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
    report = result.output

    logger.info(
        "[issue-agent] llm_complete: tokens=%d latency=%.1fs files_read=%d symbols_searched=%d tool_calls=%d",
        usage.total_tokens or 0,
        elapsed,
        len(deps.files_read),
        len(deps.symbols_searched),
        deps.tool_calls_used,
    )

    # ── Post-processing: inject fields the LLM left empty ──────────────────

    # 1. Timeline: inject pre-built if LLM left it empty
    if not report.timeline:
        logger.info("[issue-agent] injecting pre-built timeline (%d events)", len(pre_built_timeline))
        report.timeline = pre_built_timeline

    # 2. relevant_files: populate from files actually read by host code
    if not report.relevant_files and deps.files_read:
        logger.info("[issue-agent] injecting relevant_files from deps: %s", deps.files_read)
        report.relevant_files = list(dict.fromkeys(deps.files_read))

    # 3. repository_findings: backfill gaps from tracked state
    rf = report.repository_findings
    if not rf.files_found and deps.files_read:
        rf.files_found = list(dict.fromkeys(deps.files_read))
    if not rf.symbols_searched and deps.symbols_searched:
        rf.symbols_searched = list(dict.fromkeys(deps.symbols_searched))

    # 4. If no repo tool calls at all, explain in missing_context
    if deps.tool_calls_used == 0:
        logger.warning("[issue-agent] LLM made zero repo tool calls")
        if report.missing_context is None:
            report.missing_context = MissingContext(
                reason="Repository investigation was not performed by the LLM during this run",
                missing_information=["file-level call stack", "function signatures", "dependency graph"],
                recommendations=[
                    "Verify DEMO_REPOSITORY is set correctly",
                    "Check issue agent timeout (ISSUE_AGENT_TIMEOUT_MS)",
                    "Re-run the investigation for this incident",
                ],
            )

    logger.info(
        "[issue-agent] final: timeline=%d relevant_files=%d relevant_functions=%d repo_files=%d symbols=%d",
        len(report.timeline),
        len(report.relevant_files),
        len(report.relevant_functions),
        len(rf.files_found),
        len(rf.symbols_searched),
    )

    return report


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