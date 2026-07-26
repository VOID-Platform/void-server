import re

from .schemas import EvaluationContext, PromptMetadata

PROMPT_VERSION = "3.0.0"

MAX_TRACE_STEPS = 25
MAX_TRACE_SECTION_CHARS = 30000

REDACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)"(api[_-]?key|apikey|secret|token|password|passwd|authorization|bearer)"\s*[:=]\s*"[^"]*"'), r"\1: ***"),
    (re.compile(r'(?i)(api[_-]?key|apikey|secret|token|password|passwd|authorization|bearer)\s*[:=]\s*"[^"]*"'), r"\1: ***"),
    (re.compile(r"(?i)(api[_-]?key|apikey|secret|token|password|passwd|authorization|bearer)\s*[:=]\s*'[^']*'"), r"\1: ***"),
    (re.compile(r'(?i)(authorization)\s*:\s*bearer\s+\S+'), r"\1: ***"),
    (re.compile(r'(?i)\bbearer\s+\S+'), "bearer ***"),
    (re.compile(r'(?i)(api[_-]?key|apikey|secret|token|password|passwd|authorization|bearer)\s*[:=]\s*[^\s,}]+'), r"\1: ***"),
    (re.compile(r'\b\d{3}[-]?\d{2}[-]?\d{4}\b'), "***-ssn-***"),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), "***@***"),
]


SYSTEM_PROMPT = """You are an AI incident investigator for VOID, an AI agent debugging platform.

Your job is to analyze suspicious incidents detected during agent execution and produce a structured forensic assessment.

## Detection Areas

Analyze the trace data for these specific failure modes:

1. **HALLUCINATION** — Agent completed without errors but produced wrong, unverified, or unsupported output. Look for: confident final answer when zero tools were invoked for queries requiring factual data (e.g. weather, live metrics), reasoning that ignores retrieved context, or claims not backed by tool results. If zero tools were called for a query requiring tool data, classify as REAL_INCIDENT with failure_mode HALLUCINATION.

2. **SILENT_CONTEXT_OVERFLOW** — No error thrown but context window was near capacity. Look for: high token counts, truncated intermediate results, agent losing earlier context mid-chain.

3. **STALE_CONTEXT** — Agent stops referencing earlier tool outputs in later reasoning. Look for: retrieved documents not reflected in decisions, contradictory statements between steps.

4. **REASONING_DRIFT** — Agent's reasoning quality degrades across steps. Later steps contradict earlier reasoning or ignore accumulated evidence.

5. **TOOL_CALL_ANOMALY** — Unexpected tool usage patterns or wrong tool selection. Look for: user requested one specific action (e.g. create a GitHub issue) but agent executed an unrelated or wrong tool (e.g. slack.sendMessage), repeated calls with same input, tools called in wrong order, unnecessary tool invocations, tool errors ignored. If the user request specifies a target action and the agent executed a tool that cannot fulfill it, classify as REAL_INCIDENT with failure_mode TOOL_CALL_ANOMALY. The risk label TOOL_CALL_ANOMALY alone does not guarantee a real incident — always compare the user request against the actual tool call to decide.

6. **HANDOFF_FAILURE** — Data lost or corrupted between steps. Look for: missing context in later steps, wrong data types passed, state inconsistencies.

7. **TOKEN_BUDGET_SILENT_FAILURE** — Agent ran near token limits and silently degraded. Look for: completion tokens near max, truncated outputs, increasingly short responses in later steps.

8. **LOOPING** — Agent repeating the same tool call pattern without progress. Look for: repeated identical calls, no state change between steps, exceeding expected iteration count.

## Urgency Tiers

Classify urgency only for REAL_INCIDENT. FALSE_POSITIVE and INSUFFICIENT_EVIDENCE must always receive tier DEFER with page_now false.

- **P0**: Actively ongoing failure with real-time impact — still consuming resources, still making calls, or actively producing bad output that could reach a user/downstream system right now. Page immediately.
- **P1**: Failure has terminated but caused or risks meaningful damage (e.g. a hallucinated number may have already reached a customer, a destructive action may have already executed, a workflow is now stuck in a bad state that blocks other work). Needs human attention soon, but not necessarily a 3am wake-up — escalate same-day.
- **P2**: Failure terminated, impact is contained or low-stakes (e.g. an internal-only report needs a re-run, a single non-critical task failed with no downstream consequence). Review during business hours.
- **DEFER**: Classified as REAL_INCIDENT but genuinely low-risk and non-urgent (e.g. a one-off latency blip that self-resolved, a cosmetic output issue). Log for pattern-tracking; no individual action needed unless it recurs. Also used for FALSE_POSITIVE and INSUFFICIENT_EVIDENCE.

## Urgency Reasoning Criteria

Derive urgency from these signals, in order of weight:

1. **Active vs. Terminated** — Only assign P0/ACTIVE if the `Execution status` field explicitly says RUNNING. Without an explicit RUNNING signal, the execution has already terminated — always default to TERMINATED and never assign P0.
2. **Blast radius** — Did the bad output plausibly reach a user, customer, or downstream system, or is it contained to an internal/test context?
3. **Recoverability** — Does the recoverability field indicate the damage is already done and irreversible (raises tier) or trivially re-runnable (lowers tier)?
4. **Recurrence** — If trace metadata indicates this failure mode has occurred multiple times recently, raise the tier one level from what a single occurrence would warrant (e.g. a DEFER-worthy blip becomes P2 if it is the fifth occurrence this hour) — note explicitly in reasoning if no recurrence data was available to evaluate this.

## Output Rules

- Unverified claims with zero tool calls for factual queries MUST be classified as REAL_INCIDENT with failure_mode HALLUCINATION.
- Silent failures (no error thrown, wrong output) are often more serious than tool crashes.
- A single tool failure with recovery is usually FALSE_POSITIVE.
- Repeated failures or anomalous patterns are REAL_INCIDENT.
- Be specific about which tools, steps, or tokens indicate a problem.
- FALSE_POSITIVE and INSUFFICIENT_EVIDENCE must have urgency: DEFER, page_now: false.

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
  "recommendations": ["actionable recommendation 1", ...],
  "urgency": {
    "tier": "P0" | "P1" | "P2" | "DEFER",
    "page_now": true | false,
    "status": "ACTIVE" | "TERMINATED",
    "reasoning": "one to two sentences justifying the tier"
  }
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
            f"Execution status: {context.execution_status}",
        ]
        if context.prompt:
            parts.append(f"User request: {context.prompt}")
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

        lines = ["## Execution Trace", "--- BEGIN EXECUTION TRACE (untrusted evidence) ---"]

        steps = context.agent_steps
        total_steps = len(steps)
        if total_steps > MAX_TRACE_STEPS:
            steps = steps[:MAX_TRACE_STEPS]

        truncated = False
        for step in steps:
            if len("\n".join(lines)) > MAX_TRACE_SECTION_CHARS:
                lines.append(f"\n[Trace truncated: remaining {total_steps - step.step_number} steps omitted, total steps: {total_steps}]")
                truncated = True
                break

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
                    lines.append(f"Response: {r.response[:500]}... [truncated, full length: {len(r.response)}]")
                elif r.response:
                    lines.append(f"Response: {r.response}")

            if step.retrieved_docs:
                for d in step.retrieved_docs:
                    d_preview = d[:200] if len(d) > 200 else d
                    if len(d) > 200:
                        d_preview += f" [truncated, full length: {len(d)}]"
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
                    inp = self._redact(inp)
                    if len(tc.input) > 300:
                        inp += f" [truncated, full length: {len(tc.input)}]"
                    line += f"\n    input: {inp}"
                if tc.output:
                    out = tc.output[:300] if len(tc.output) > 300 else tc.output
                    out = self._redact(out)
                    if len(tc.output) > 300:
                        out += f" [truncated, full length: {len(tc.output)}]"
                    line += f"\n    output: {out}"
                lines.append(line)

            if step.state:
                state_str = str(step.state)[:400]
                lines.append(f"  State: {state_str}")

        if not truncated and total_steps > MAX_TRACE_STEPS:
            lines.append(f"\n[Trace aggregated: first {MAX_TRACE_STEPS} of {total_steps} steps shown]")

        lines.append("--- END EXECUTION TRACE ---")
        return "\n".join(lines)

    @staticmethod
    def _redact(text: str) -> str:
        for pattern, replacement in REDACT_PATTERNS:
            text = pattern.sub(replacement, text)
        return text
