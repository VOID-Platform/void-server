import json
import logging
import time
from typing import Any
from pydantic_ai import Agent, RunContext, ModelHTTPError

from issue_agent.schemas import IncidentSnapshot, EngineeringReport
from issue_agent.evidence import extract_evidence


logger = logging.getLogger(__name__)
_log = logger.getChild("structured")


class IssueAgentDeps:
    def __init__(self, repo: Any):
        self.repo = repo
        self.files_read: list[str] = []
        self.tokens_used: int = 0


SYSTEM_PROMPT = """You are a senior engineer investigating an AI system incident.

Your task:
1. Review the incident snapshot (execution traces, evaluator output, telemetry).
2. Extract structured evidence about what went wrong.
3. Use repository tools to find the relevant code.
4. Search for symbols, filenames, and function names from the trace.
5. Build a code graph around suspected files and traverse it.
6. Read the smallest set of functions needed to understand the bug.
7. Write an engineering report with root cause, evidence, and suggested fix.
8. Create a GitHub issue with the report (skip if not available).

Rules:
- Search before reading — minimize context.
- Only read files relevant to the incident.
- The confidence score must match the evidence strength.
- Fill ALL fields of the report: summary, root_cause, evidence, suspected_components, relevant_files, relevant_functions, suggested_investigation, suggested_fix, suggested_tests, confidence.
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
        results = ctx.deps.repo.search_symbol(query)
        ctx.deps.tokens_used += 1
        return json.dumps(results, indent=2)

    @agent.tool
    def read_file(ctx: RunContext[IssueAgentDeps], path: str) -> str:
        content = ctx.deps.repo.read_file(path)
        ctx.deps.files_read.append(path)
        ctx.deps.tokens_used += 1
        if content is None:
            return f"File not found: {path}"
        return content

    @agent.tool
    def build_code_graph(ctx: RunContext[IssueAgentDeps], file_paths: list[str]) -> str:
        graph = ctx.deps.repo.build_code_graph(file_paths)
        ctx.deps.tokens_used += 1
        return graph.model_dump_json(indent=2)

    import os
    if not os.environ.get("VOID_DEV_MODE"):
        @agent.tool
        def create_github_issue(ctx: RunContext[IssueAgentDeps], title: str, body: str) -> str:
            url = ctx.deps.repo.create_issue(title, body)
            ctx.deps.tokens_used += 1
            if url:
                logger.info("Created GitHub issue: %s", url)
                return f"Issue created: {url}"
            return "Failed to create issue"

    return agent


def run_issue_agent(
    snapshot: IncidentSnapshot,
    repo: Any,
    max_retries: int = 5,
) -> EngineeringReport | None:
    evidence = extract_evidence(snapshot)
    deps = IssueAgentDeps(repo=repo)
    input_data = {
        "incident_id": snapshot.incident_id,
        "failure_modes": snapshot.evaluation.failure_modes,
        "confidence": snapshot.evaluation.confidence,
        "reasoning": snapshot.evaluation.reasoning,
        "severity": snapshot.evaluation.severity,
        "evidence": [e.model_dump() for e in evidence],
        "agent_steps": [
            {
                "step_type": s.step_type,
                "tool_calls": [t.model_dump() for t in s.tool_calls],
            }
            for s in snapshot.execution_trace.agent_steps
        ],
        "model": snapshot.execution_trace.model,
        "tokens_used": snapshot.execution_trace.tokens_used,
    }
    input_json = json.dumps(input_data, indent=2)
    input_size = len(input_json)

    agent = _build_agent()

    last_error: Exception | None = None
    start_time = time.monotonic()

    for attempt in range(max_retries):
        try:
            result = agent.run_sync(input_json, deps=deps)
            break
        except ModelHTTPError as e:
            last_error = e
            if e.status_code != 429:
                _log.error("model_http_error", extra={"status": e.status_code, "model": e.model_name, "body": str(e.body)})
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
                _log.info("tool_call", extra={"tool": part.tool_name, "tool_args": str(part.args)[:2000]})
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


def _parse_retry_delay(body: object, default: float = 2.0) -> float:
    if isinstance(body, dict):
        raw = body.get("retryDelay", body.get("retry_delay", body.get("Retry-After", None)))
        if raw is not None:
            try:
                if isinstance(raw, str) and raw.endswith("s"):
                    return float(raw[:-1])
                return float(raw)
            except (ValueError, TypeError):
                pass
    return default * 2