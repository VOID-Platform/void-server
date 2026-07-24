from issue_agent.schemas import IncidentSnapshot, Evidence


def extract_evidence(snapshot: IncidentSnapshot) -> list[Evidence]:
    evidence_list = []
    for fm in snapshot.evaluation.failure_modes:
        trace_lines = []
        for step in snapshot.execution_trace.agent_steps:
            if step.tool_calls:
                for tc in step.tool_calls:
                    if not tc.success:
                        trace_lines.append(
                            f"Tool '{tc.name}' failed: {tc.error or 'unknown error'}"
                        )
        evidence_list.append(
            Evidence(
                failure_mode=fm,
                summary=snapshot.evaluation.reasoning,
                supporting_trace=trace_lines or ["No specific trace captured"],
                confidence=snapshot.evaluation.confidence,
            )
        )
    return evidence_list