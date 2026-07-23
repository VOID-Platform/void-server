from .schemas import Evaluation, EvaluationContext

REAL_LABELS = {"HIGH_LATENCY", "TOKEN_OVERFLOW", "CRASH_LOOP", "ESCALATION"}
POSITIVE_LABELS = {"TRANSIENT_ERROR", "RATE_LIMIT"}


class ConfidenceScorer:
    def score(
        self,
        model_confidence: float,
        context: EvaluationContext,
        evaluation: Evaluation,
    ) -> float:
        score = model_confidence

        label_set = set(context.labels)
        classification = evaluation.classification
        has_real_labels = bool(label_set & REAL_LABELS)
        has_positive_labels = bool(label_set & POSITIVE_LABELS)

        if classification == "REAL_INCIDENT" and has_real_labels:
            score = min(score + 0.1, 1.0)

        if classification == "FALSE_POSITIVE" and has_positive_labels:
            score = min(score + 0.05, 1.0)

        if classification == "REAL_INCIDENT" and has_positive_labels:
            score = max(score - 0.15, 0.0)

        if classification == "FALSE_POSITIVE" and has_real_labels:
            score = max(score - 0.2, 0.0)

        if context.occurrence >= 3:
            score = min(score + 0.05, 1.0)

        if not context.first_scene and not context.last_scene:
            score = max(score - 0.1, 0.0)

        if not evaluation.reasoning:
            score = max(score - 0.1, 0.0)

        if classification == "INSUFFICIENT_EVIDENCE":
            score = min(score, 0.5)

        tel = context.telemetry

        if tel and tel.failed_tool_calls and tel.failed_tool_calls > 0:
            if classification == "REAL_INCIDENT":
                score = min(score + 0.05, 1.0)
            elif classification == "FALSE_POSITIVE":
                score = max(score - 0.1, 0.0)

        if tel and tel.retry_count and tel.retry_count >= 3:
            score = min(score + 0.05, 1.0)

        if tel and tel.tool_call_count is not None:
            if tel.tool_call_count == 0 and classification == "INSUFFICIENT_EVIDENCE":
                score = max(score - 0.05, 0.0)

        if context.agent_steps:
            silent_failures = 0
            for step in context.agent_steps:
                for tc in step.tool_calls:
                    if tc.success and tc.output is None:
                        silent_failures += 1
            if silent_failures > 0 and classification == "REAL_INCIDENT":
                score = min(score + 0.05, 1.0)

        return round(score, 2)
