from .schemas import EvaluationContext, PromptMetadata

PROMPT_VERSION = "2.0.0"

SYSTEM_PROMPT = """You are an AI incident investigator for VOID, an AI agent debugging platform.

Your job is to analyze suspicious incidents detected during agent execution and produce a structured forensic assessment.

## Detection Areas

Analyze the trace data for these specific failure modes:

1. **HALLUCINATION** — Agent completed without errors but produced wrong or unsupported output. Look for: confident final answer that contradicts tool outputs, reasoning that ignores retrieved context, or claims not backed by tool results.

2. **SILENT_CONTEXT_OVERFLOW** — No error thrown but context window was near capacity. Look for: high token counts, truncated intermediate results, agent losing earlier context mid-chain.

3. **STALE_CONTEXT** — Agent stops referencing earlier tool outputs in later reasoning. Look for: retrieved documents not reflected in decisions, contradictory statements between steps.

4. **REASONING_DRIFT** — Agent's reasoning quality degrades across steps. Later steps contradict earlier reasoning or ignore accumulated evidence.

5. **TOOL_CALL_ANOMALY** — Unexpected tool usage patterns. Look for: repeated calls with same input, tools called in wrong order, unnecessary tool invocations, tool errors ignored.

6. **HANDOFF_FAILURE** — Data lost or corrupted between steps. Look for: missing context in later steps, wrong data types passed, state inconsistencies.

7. **TOKEN_BUDGET_SILENT_FAILURE** — Agent ran near token limits and silently degraded. Look for: completion tokens near max, truncated outputs, increasingly short responses in later steps.

8. **LOOPING** — Agent repeating the same tool call pattern without progress. Look for: repeated identical calls, no state change between steps, exceeding expected iteration count.

## Output Rules

- If the trace is empty or minimal, classify as INSUFFICIENT_EVIDENCE.
- Silent failures (no error thrown, wrong output) are often more serious than tool crashes.
- A single tool failure with recovery is usually FALSE_POSITIVE.
- Repeated failures or anomalous patterns are REAL_INCIDENT.
- Be specific about which tools, steps, or tokens indicate a problem.

Respond ONLY with valid JSON matching this schema:
{
  "summary": "brief description of the incident, key findings, and your assessment",
  "classification": "REAL_INCIDENT" | "FALSE_POSITIVE" | "INSUFFICIENT_EVIDENCE",
  "recoverability": "RECOVERABLE" | "NON_RECOVERABLE" | "UNKNOWN",
  "confidence": 0.0-1.0,
  "failure_modes": ["HALLUCINATION" | "SILENT_CONTEXT_OVERFLOW" | "STALE_CONTEXT" | "REASONING_DRIFT" | "TOOL_CALL_ANOMALY" | "HANDOFF_FAILURE" | "TOKEN_BUDGET_SILENT_FAILURE" | "LOOPING" | "NONE_DETECTED"],
  "suspected_root_cause": "what likely caused this incident",
  "suspected_components": ["component1", "component2"],
  "reasoning": ["evidence-based reason 1", "evidence-based reason 2", ...],
  "recommendations": ["actionable recommendation 1", ...]
}"""


class PromptBuilder:
    def build(self, context: EvaluationContext) -> PromptMetadata:
        incident_section = self._build_incident_section(context)
        trace_section = self._build_trace_section(context)
        full = f"{SYSTEM_PROMPT}\n\n---\n\n{incident_section}\n\n{trace_section}"
        return PromptMetadata(
            prompt_version=PROMPT_VERSION,
            prompt=full,
            temperature=0.2,
        )

    def _build_incident_section(self, context: EvaluationContext) -> str:
        parts = [
            "## Incident",
            f"Title: {context.title}",
            f"Severity: {context.severity}",
            f"Fingerprint: {context.fingerprint}",
            f"Occurrence count: {context.occurrence}",
            f"Execution ID: {context.execution_id}",
            f"Trace ID: {context.trace_id}",
        ]
        if context.first_scene:
            parts.append(f"First seen scene: {context.first_scene}")
        if context.last_scene:
            parts.append(f"Last seen scene: {context.last_scene}")
        if context.labels:
            parts.append(f"Risk labels: {', '.join(context.labels)}")
        if context.telemetry:
            t = context.telemetry
            tel = []
            if t.total_latency_ms is not None:
                tel.append(f"Total latency: {t.total_latency_ms}ms")
            if t.total_prompt_tokens is not None:
                tel.append(f"Prompt tokens: {t.total_prompt_tokens}")
            if t.total_completion_tokens is not None:
                tel.append(f"Completion tokens: {t.total_completion_tokens}")
            if t.tool_call_count is not None:
                tel.append(f"Tool calls: {t.tool_call_count}")
            if t.failed_tool_calls is not None:
                tel.append(f"Failed calls: {t.failed_tool_calls}")
            if t.retry_count is not None:
                tel.append(f"Retries: {t.retry_count}")
            parts.append("Telemetry: " + ", ".join(tel))
        return "\n".join(parts)

    def _build_trace_section(self, context: EvaluationContext) -> str:
        if not context.agent_steps:
            return "## Execution Trace\nNo trace data available."

        lines = ["## Execution Trace"]
        for step in context.agent_steps:
            lines.append(f"\n### Step {step.step_number}")

            if step.llm_response:
                r = step.llm_response
                info = []
                if r.model:
                    info.append(f"model={r.model}")
                if r.prompt_tokens is not None:
                    info.append(f"prompt_tokens={r.prompt_tokens}")
                if r.completion_tokens is not None:
                    info.append(f"completion_tokens={r.completion_tokens}")
                lines.append(f"LLM: {', '.join(info) if info else 'called'}")
                if r.response and len(r.response) > 500:
                    lines.append(f"Response: {r.response[:500]}...")
                elif r.response:
                    lines.append(f"Response: {r.response}")

            if step.retrieved_docs:
                for d in step.retrieved_docs:
                    d_preview = d[:200] if len(d) > 200 else d
                    lines.append(f"Retrieved: {d_preview}")

            for tc in step.tool_calls:
                status = "OK" if tc.success else "ERROR"
                line = f"  Tool: {tc.name} [{status}]"
                if tc.latency_ms is not None:
                    line += f" ({tc.latency_ms}ms)"
                if tc.error:
                    line += f" error={tc.error}"
                if tc.retry_count:
                    line += f" retries={tc.retry_count}"
                if tc.input:
                    inp = tc.input[:300] if len(tc.input) > 300 else tc.input
                    line += f"\n    input: {inp}"
                if tc.output:
                    out = tc.output[:300] if len(tc.output) > 300 else tc.output
                    line += f"\n    output: {out}"
                lines.append(line)

            if step.state:
                state_str = str(step.state)[:400]
                lines.append(f"  State: {state_str}")

        return "\n".join(lines)
