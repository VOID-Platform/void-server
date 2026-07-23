from datetime import datetime, timezone

from .schemas import Evaluation, EvaluationContext, FullEvaluation, EvaluationMetadata
from .context_builder import ContextBuilder
from .prompt_builder import PromptBuilder
from .gemini_client import GeminiClient
from .validator import Validator
from .scorer import ConfidenceScorer


class Agent:
    def __init__(
        self,
        context_builder: ContextBuilder | None = None,
        prompt_builder: PromptBuilder | None = None,
        gemini_client: GeminiClient | None = None,
        validator: Validator | None = None,
        scorer: ConfidenceScorer | None = None,
    ):
        self.context_builder = context_builder or ContextBuilder()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.gemini_client = gemini_client or GeminiClient()
        self.validator = validator or Validator()
        self.scorer = scorer or ConfidenceScorer()

    def evaluate(self, incident_data: dict) -> FullEvaluation | None:
        context = self.context_builder.build(incident_data)

        prompt_meta = self.prompt_builder.build(context)

        raw = self.gemini_client.evaluate(prompt_meta)

        result = self.validator.validate(raw)
        if not result.valid or result.evaluation is None:
            return None

        evaluation = result.evaluation

        final_confidence = self.scorer.score(
            evaluation.confidence, context, evaluation
        )
        evaluation.confidence = final_confidence

        metadata = EvaluationMetadata(
            prompt_version=prompt_meta.prompt_version,
            model_version="gemini-3.1-flash-lite",
            model_temperature=prompt_meta.temperature,
            evaluated_at=datetime.now(timezone.utc),
        )

        return FullEvaluation(evaluation=evaluation, metadata=metadata)
