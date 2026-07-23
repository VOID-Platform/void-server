from .schemas import (
    EvaluationContext,
    AgentStep,
    ToolCall,
    LLMResponse,
    TelemetrySummary,
)


class ContextBuilder:
    def build(self, incident_data: dict) -> EvaluationContext:
        exec_status = incident_data.get("execution_status")
        if exec_status not in ("RUNNING", "COMPLETED", "FAILED"):
            exec_status = "COMPLETED"
        return EvaluationContext(
            incident_id=incident_data["id"],
            fingerprint=incident_data["fingerprint"],
            title=incident_data.get("title", ""),
            severity=incident_data.get("severity", ""),
            labels=incident_data.get("latest_labels", [])
            or incident_data.get("labels", []),
            occurrence=incident_data.get("occurrence", 1),
            trace_id=incident_data.get("trace_id", ""),
            execution_id=incident_data.get("execution_id", ""),
            first_scene=incident_data.get("first_scene", ""),
            last_scene=incident_data.get("last_scene", ""),
            agent_steps=self._parse_steps(incident_data.get("agent_steps", [])),
            telemetry=self._parse_telemetry(incident_data.get("telemetry")),
            execution_status=exec_status,
        )

    def _parse_steps(self, steps: list[dict]) -> list[AgentStep]:
        return [AgentStep(
            step_number=s.get("step_number", i),
            tool_calls=[ToolCall(**tc) for tc in s.get("tool_calls", [])],
            llm_response=LLMResponse(**s["llm_response"]) if s.get("llm_response") else None,
            state=s.get("state"),
            retrieved_docs=s.get("retrieved_docs", []),
        ) for i, s in enumerate(steps)]

    def _parse_telemetry(self, t: dict | None) -> TelemetrySummary | None:
        if not t:
            return None
        return TelemetrySummary(**t)
