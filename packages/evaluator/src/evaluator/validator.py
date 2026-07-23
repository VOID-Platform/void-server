import json
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError

from .schemas import Evaluation


VALID_CLASSIFICATIONS = {"REAL_INCIDENT", "FALSE_POSITIVE", "INSUFFICIENT_EVIDENCE"}
VALID_RECOVERABILITIES = {"RECOVERABLE", "NON_RECOVERABLE", "UNKNOWN"}
VALID_URGENCY_TIERS = {"P0", "P1", "P2", "DEFER"}
VALID_URGENCY_STATUSES = {"ACTIVE", "TERMINATED"}
VALID_FAILURE_MODES = {
    "HALLUCINATION", "SILENT_CONTEXT_OVERFLOW", "STALE_CONTEXT",
    "REASONING_DRIFT", "TOOL_CALL_ANOMALY", "HANDOFF_FAILURE",
    "TOKEN_BUDGET_SILENT_FAILURE", "LOOPING", "NONE_DETECTED",
}


@dataclass
class ValidationResult:
    valid: bool
    evaluation: Evaluation | None
    errors: list[str]


class Validator:
    def validate(self, raw: str) -> ValidationResult:
        errors: list[str] = []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            return ValidationResult(
                valid=False,
                evaluation=None,
                errors=[f"Malformed JSON: {e}"],
            )

        if not isinstance(data, dict):
            return ValidationResult(
                valid=False,
                evaluation=None,
                errors=[f"Expected JSON object, got {type(data).__name__}"],
            )

        required_fields = [
            "summary",
            "classification",
            "recoverability",
            "confidence",
            "reasoning",
            "recommendations",
            "urgency",
        ]
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")

        if errors:
            return ValidationResult(valid=False, evaluation=None, errors=errors)

        classification = data.get("classification")
        if classification not in VALID_CLASSIFICATIONS:
            errors.append(
                f"Invalid classification: {classification!r}. "
                f"Must be one of {VALID_CLASSIFICATIONS}"
            )

        recoverability = data.get("recoverability")
        if recoverability not in VALID_RECOVERABILITIES:
            errors.append(
                f"Invalid recoverability: {recoverability!r}. "
                f"Must be one of {VALID_RECOVERABILITIES}"
            )

        confidence = data.get("confidence")
        if not isinstance(confidence, (int, float)):
            errors.append(f"confidence must be a number, got {type(confidence).__name__}")
        elif confidence < 0.0 or confidence > 1.0:
            errors.append(f"confidence must be between 0.0 and 1.0, got {confidence}")

        reasoning = data.get("reasoning")
        if not isinstance(reasoning, list) or not reasoning:
            errors.append("reasoning must be a non-empty list")

        recommendations = data.get("recommendations")
        if not isinstance(recommendations, list):
            errors.append("recommendations must be a list")

        failure_modes = data.get("failure_modes")
        if failure_modes is not None:
            if not isinstance(failure_modes, list):
                errors.append("failure_modes must be a list")
            else:
                for mode in failure_modes:
                    if mode not in VALID_FAILURE_MODES:
                        errors.append(
                            f"Invalid failure_mode: {mode!r}. "
                            f"Must be one of {VALID_FAILURE_MODES}"
                        )

        urgency = data.get("urgency")
        if not isinstance(urgency, dict):
            errors.append("urgency must be an object")
        else:
            tier = urgency.get("tier")
            if tier not in VALID_URGENCY_TIERS:
                errors.append(
                    f"Invalid urgency.tier: {tier!r}. "
                    f"Must be one of {VALID_URGENCY_TIERS}"
                )
            status = urgency.get("status")
            if status not in VALID_URGENCY_STATUSES:
                errors.append(
                    f"Invalid urgency.status: {status!r}. "
                    f"Must be one of {VALID_URGENCY_STATUSES}"
                )
            page_now = urgency.get("page_now")
            if not isinstance(page_now, bool):
                errors.append("urgency.page_now must be a boolean")
            if not isinstance(urgency.get("reasoning"), str) or not urgency.get("reasoning"):
                errors.append("urgency.reasoning must be a non-empty string")

            classification = data.get("classification")
            if classification in {"FALSE_POSITIVE", "INSUFFICIENT_EVIDENCE"}:
                if tier != "DEFER":
                    errors.append(
                        f"urgency.tier must be DEFER for {classification}, got {tier}"
                    )
                if page_now is not False:
                    errors.append(
                        f"urgency.page_now must be false for {classification}"
                    )

        if errors:
            return ValidationResult(valid=False, evaluation=None, errors=errors)

        try:
            evaluation = Evaluation(**data)
        except PydanticValidationError as e:
            return ValidationResult(
                valid=False,
                evaluation=None,
                errors=[f"Pydantic validation failed: {e}"],
            )

        return ValidationResult(valid=True, evaluation=evaluation, errors=[])
