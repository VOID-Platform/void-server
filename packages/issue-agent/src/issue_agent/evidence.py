from issue_agent.schemas import IncidentSnapshot, Evidence


def extract_evidence(snapshot: IncidentSnapshot) -> list[Evidence]:
    """Build Evidence objects for each failure mode, grounded in the execution trace.

    Populates supporting_trace with tool names, latencies, inputs, errors, and any
    planner reasoning text so the LLM has concrete trace detail to cite.
    """
    evidence_list = []

    # Collect all trace details once, indexed by step
    trace_lines: list[str] = []
    for si, step in enumerate(snapshot.execution_trace.agent_steps):
        step_label = f"Step {si} [{step.step_type}]"

        # Include the agent's own reasoning / planner output if available
        if step.planner_output:
            preview = step.planner_output[:200].strip()
            trace_lines.append(f"{step_label} — agent reasoning: {preview}")

        for tc in step.tool_calls:
            status = "✓" if tc.success else "✗"
            detail = f"{step_label} — tool {tc.name} [{status}]"
            if tc.latency_ms is not None:
                detail += f" ({tc.latency_ms:.0f}ms)"
            if tc.input:
                detail += f" input={tc.input[:120]}"
            if tc.error:
                detail += f" → ERROR: {tc.error}"
            elif tc.output:
                detail += f" → {tc.output[:120]}"
            trace_lines.append(detail)

        if not step.tool_calls and not step.planner_output:
            trace_lines.append(f"{step_label} — no tool calls, no planner output")

    if not trace_lines:
        trace_lines = ["No trace data available"]

    for fm in snapshot.evaluation.failure_modes:
        evidence_list.append(
            Evidence(
                failure_mode=fm,
                summary=snapshot.evaluation.reasoning,
                supporting_trace=trace_lines,
                confidence=snapshot.evaluation.confidence,
            )
        )

    return evidence_list