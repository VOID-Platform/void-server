"""
e2e tests for the Evaluator pipeline.

Run from packages/evaluator:
    PYTHONPATH=src .venv/bin/python3 -m unittest tests/test_evaluator_e2e.py -v

Run from repo root:
    PYTHONPATH=packages/evaluator/src \\
        packages/evaluator/.venv/bin/python3 \\
        -m unittest packages/evaluator/tests/test_evaluator_e2e.py -v
"""

import json
import os
import unittest
from dataclasses import dataclass

from evaluator.schemas import (
    Evaluation,
    EvaluationContext,
    EvaluationMetadata,
    FullEvaluation,
    PromptMetadata,
    ToolCall,
    AgentStep,
    TelemetrySummary,
)
from evaluator.context_builder import ContextBuilder
from evaluator.prompt_builder import PromptBuilder, PROMPT_VERSION
from evaluator.validator import Validator
from evaluator.scorer import ConfidenceScorer, REAL_LABELS, POSITIVE_LABELS
from evaluator.agent import Agent


URGENCY_REAL_P0 = {
    "tier": "P0", "page_now": True, "status": "ACTIVE",
    "reasoning": "Failure is actively ongoing and consuming resources.",
}
URGENCY_REAL_P1 = {
    "tier": "P1", "page_now": False, "status": "TERMINATED",
    "reasoning": "Failure terminated but bad output may have reached downstream.",
}
URGENCY_REAL_P2 = {
    "tier": "P2", "page_now": False, "status": "TERMINATED",
    "reasoning": "Failure terminated with contained impact, review during business hours.",
}
URGENCY_DEFER = {
    "tier": "DEFER", "page_now": False, "status": "TERMINATED",
    "reasoning": "Test fixture with no real-world urgency.",
}

VALID_EVAL_JSON = json.dumps({
    "summary": "Test incident summary",
    "classification": "REAL_INCIDENT",
    "recoverability": "RECOVERABLE",
    "confidence": 0.85,
    "failure_modes": ["NONE_DETECTED"],
    "suspected_root_cause": "",
    "suspected_components": [],
    "reasoning": ["reason 1", "reason 2"],
    "recommendations": ["recommendation 1"],
    "urgency": URGENCY_REAL_P2,
})


@dataclass
class MockGeminiClient:
    response: str = VALID_EVAL_JSON

    def evaluate(self, prompt_meta: PromptMetadata) -> str:
        try:
            parsed = json.loads(self.response)
        except json.JSONDecodeError:
            return self.response
        if "urgency" not in parsed:
            parsed["urgency"] = {
                "tier": "DEFER", "page_now": False, "status": "TERMINATED",
                "reasoning": "Default urgency for test mock.",
            }
        return json.dumps(parsed)


SAMPLE_INCIDENT = {
    "id": "test-001",
    "fingerprint": "abc123",
    "title": "SUSPICIOUS: HIGH_LATENCY + TOKEN_OVERFLOW",
    "severity": "SUSPICIOUS",
    "status": "OPEN",
    "confidence": 0.0,
    "trace_id": "trace-001",
    "execution_id": "exec-001",
    "first_scene": "tool_call:weather_api",
    "last_scene": "tool_call:weather_api",
    "occurrence": 1,
    "latest_labels": ["HIGH_LATENCY", "TOKEN_OVERFLOW"],
}

SAMPLE_INCIDENT_NO_LABELS = {
    "id": "test-002",
    "fingerprint": "def456",
    "title": "SUSPICIOUS",
    "severity": "SUSPICIOUS",
    "trace_id": "",
    "execution_id": "exec-002",
    "occurrence": 5,
}

SAMPLE_INCIDENT_WITH_TRACE = {
    "id": "test-003",
    "fingerprint": "ghi789",
    "title": "SUSPICIOUS: HIGH_LATENCY + TOKEN_OVERFLOW",
    "severity": "SUSPICIOUS",
    "status": "OPEN",
    "confidence": 0.0,
    "trace_id": "trace-003",
    "execution_id": "exec-003",
    "first_scene": "tool_call:search",
    "last_scene": "tool_call:generate",
    "occurrence": 1,
    "latest_labels": ["HIGH_LATENCY", "TOOL_FAILURE"],
    "agent_steps": [
        {
            "step_number": 1,
            "llm_response": {
                "model": "gpt-4",
                "response": "Let me search for the answer.",
                "prompt_tokens": 500,
                "completion_tokens": 50,
            },
            "tool_calls": [
                {
                    "name": "search",
                    "input": '{"query": "latest prices"}',
                    "output": '{"results": ["item1", "item2"]}',
                    "latency_ms": 1200,
                    "success": True,
                },
            ],
            "retrieved_docs": ["doc content about pricing"],
        },
        {
            "step_number": 2,
            "llm_response": {
                "model": "gpt-4",
                "response": "Based on search results, the answer is X.",
                "prompt_tokens": 600,
                "completion_tokens": 100,
            },
            "tool_calls": [
                {
                    "name": "generate",
                    "input": '{"prompt": "summarize findings"}',
                    "output": "Final summary of findings.",
                    "latency_ms": 3000,
                    "success": True,
                },
            ],
        },
    ],
    "telemetry": {
        "total_latency_ms": 4200,
        "total_prompt_tokens": 1100,
        "total_completion_tokens": 150,
        "tool_call_count": 2,
        "failed_tool_calls": 0,
        "retry_count": 0,
    },
}

SAMPLE_INCIDENT_SILENT_FAILURE = {
    "id": "test-004",
    "fingerprint": "silent001",
    "title": "SUSPICIOUS",
    "severity": "SUSPICIOUS",
    "trace_id": "trace-silent",
    "execution_id": "exec-silent",
    "occurrence": 1,
    "agent_steps": [
        {
            "step_number": 1,
            "tool_calls": [
                {"name": "search", "success": True, "output": None,
                 "input": '{"q": "data"}', "latency_ms": 100},
            ],
            "llm_response": {"response": "Confident wrong answer.", "completion_tokens": 200},
        },
    ],
    "telemetry": {"tool_call_count": 1, "failed_tool_calls": 0},
}


# ─── Golden Dataset Tests ────────────────────────────────────────────────

class GoldenDatasetTest(unittest.TestCase):
    def test_golden_dataset_example(self):
        dataset_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "evaluation_dataset", "incidents", "example",
        )
        incident_path = os.path.join(dataset_dir, "incident.json")
        expected_path = os.path.join(dataset_dir, "expected.json")

        with open(incident_path) as f:
            incident = json.load(f)
        with open(expected_path) as f:
            expected = json.load(f)

        mock = MockGeminiClient(response=json.dumps({
            "summary": "High latency and token overflow indicate a real performance problem",
            "classification": expected["classification"],
            "recoverability": expected["recoverability"],
            "confidence": 0.8,
            "failure_modes": ["NONE_DETECTED"],
            "suspected_root_cause": "",
            "suspected_components": [],
            "reasoning": expected["reasoning"],
            "recommendations": expected["recommendations"],
            "urgency": URGENCY_REAL_P2,
        }))

        agent = Agent(gemini_client=mock)
        result = agent.evaluate(incident)

        self.assertIsNotNone(result)
        self.assertEqual(result.evaluation.classification, expected["classification"])
        self.assertEqual(result.evaluation.recoverability, expected["recoverability"])
        self.assertEqual(result.evaluation.reasoning, expected["reasoning"])
        self.assertEqual(result.evaluation.recommendations, expected["recommendations"])

    def test_golden_dataset_confidence_routing(self):
        mock = MockGeminiClient(response=json.dumps({
            "summary": "test", "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE", "confidence": 0.8,
            "failure_modes": ["NONE_DETECTED"],
            "suspected_root_cause": "", "suspected_components": [],
            "reasoning": ["test"], "recommendations": ["test"],
        }))
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT)
        final = result.evaluation.confidence
        self.assertGreaterEqual(final, 0.70)
        self.assertLessEqual(final, 1.0)

        mock_low = MockGeminiClient(response=json.dumps({
            "summary": "not enough data", "classification": "INSUFFICIENT_EVIDENCE",
            "recoverability": "UNKNOWN", "confidence": 0.3,
            "failure_modes": ["NONE_DETECTED"],
            "suspected_root_cause": "", "suspected_components": [],
            "reasoning": ["not enough data"], "recommendations": ["collect more data"],
        }))
        agent_low = Agent(gemini_client=mock_low)
        result_low = agent_low.evaluate(SAMPLE_INCIDENT)
        self.assertLess(result_low.evaluation.confidence, 0.70)


# ─── Context Builder Tests ───────────────────────────────────────────────

class ContextBuilderTest(unittest.TestCase):
    def test_build_full(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT)
        self.assertIsInstance(ctx, EvaluationContext)
        self.assertEqual(ctx.incident_id, "test-001")
        self.assertEqual(ctx.fingerprint, "abc123")
        self.assertEqual(ctx.title, "SUSPICIOUS: HIGH_LATENCY + TOKEN_OVERFLOW")
        self.assertEqual(ctx.severity, "SUSPICIOUS")
        self.assertEqual(ctx.labels, ["HIGH_LATENCY", "TOKEN_OVERFLOW"])
        self.assertEqual(ctx.occurrence, 1)
        self.assertEqual(ctx.trace_id, "trace-001")
        self.assertEqual(ctx.execution_id, "exec-001")
        self.assertEqual(ctx.first_scene, "tool_call:weather_api")
        self.assertEqual(ctx.last_scene, "tool_call:weather_api")

    def test_build_minimal(self):
        ctx = ContextBuilder().build({"id": "x", "fingerprint": "y", "execution_id": "z"})
        self.assertEqual(ctx.title, "")
        self.assertEqual(ctx.severity, "")
        self.assertEqual(ctx.labels, [])
        self.assertEqual(ctx.occurrence, 1)
        self.assertEqual(ctx.trace_id, "")
        self.assertEqual(ctx.first_scene, "")
        self.assertEqual(ctx.last_scene, "")

    def test_build_fallback_labels(self):
        ctx = ContextBuilder().build({
            "id": "x", "fingerprint": "y", "execution_id": "z",
            "labels": ["HIGH_LATENCY"],
        })
        self.assertEqual(ctx.labels, ["HIGH_LATENCY"])

    def test_build_with_trace(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT_WITH_TRACE)
        self.assertEqual(len(ctx.agent_steps), 2)
        self.assertEqual(ctx.agent_steps[0].step_number, 1)
        self.assertEqual(len(ctx.agent_steps[0].tool_calls), 1)
        self.assertEqual(ctx.agent_steps[0].tool_calls[0].name, "search")
        self.assertEqual(ctx.agent_steps[0].tool_calls[0].latency_ms, 1200)
        self.assertIsNotNone(ctx.agent_steps[0].llm_response)
        self.assertEqual(ctx.agent_steps[0].llm_response.model, "gpt-4")
        self.assertEqual(len(ctx.agent_steps[0].retrieved_docs), 1)
        self.assertIsNotNone(ctx.telemetry)
        self.assertEqual(ctx.telemetry.total_latency_ms, 4200)
        self.assertEqual(ctx.telemetry.tool_call_count, 2)


# ─── Prompt Builder Tests ────────────────────────────────────────────────

class PromptBuilderTest(unittest.TestCase):
    def test_prompt_contains_incident_details(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT)
        prompt = PromptBuilder().build(ctx)
        self.assertEqual(prompt.prompt_version, PROMPT_VERSION)
        self.assertEqual(prompt.temperature, 0.2)
        self.assertIn("tool_call:weather_api", prompt.prompt)
        self.assertIn("HIGH_LATENCY", prompt.prompt)
        self.assertIn("TOKEN_OVERFLOW", prompt.prompt)
        self.assertIn("REAL_INCIDENT", prompt.prompt)
        self.assertIn("JSON", prompt.prompt)

    def test_prompt_schema_instruction(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT_NO_LABELS)
        prompt = PromptBuilder().build(ctx)
        self.assertIn("summary", prompt.prompt)
        self.assertIn("classification", prompt.prompt)
        self.assertIn("confidence", prompt.prompt)

    def test_prompt_includes_trace_when_present(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT_WITH_TRACE)
        prompt = PromptBuilder().build(ctx)
        self.assertIn("Execution Trace", prompt.prompt)
        self.assertIn("search", prompt.prompt)
        self.assertIn("gpt-4", prompt.prompt)
        self.assertIn("1200.0ms", prompt.prompt)

    def test_prompt_shows_no_trace_when_empty(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT)
        prompt = PromptBuilder().build(ctx)
        self.assertIn("No trace data available", prompt.prompt)

    def test_prompt_contains_failure_mode_detection_areas(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT)
        prompt = PromptBuilder().build(ctx)
        self.assertIn("HALLUCINATION", prompt.prompt)
        self.assertIn("SILENT_CONTEXT_OVERFLOW", prompt.prompt)
        self.assertIn("LOOPING", prompt.prompt)
        self.assertIn("failure_modes", prompt.prompt)


# ─── Validator Tests ─────────────────────────────────────────────────────

class ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.validator = Validator()

    def test_valid_json(self):
        result = self.validator.validate(VALID_EVAL_JSON)
        self.assertTrue(result.valid)
        self.assertIsNotNone(result.evaluation)
        self.assertEqual(result.evaluation.classification, "REAL_INCIDENT")
        self.assertEqual(result.evaluation.recoverability, "RECOVERABLE")
        self.assertEqual(result.evaluation.confidence, 0.85)
        self.assertEqual(result.evaluation.failure_modes, ["NONE_DETECTED"])
        self.assertEqual(result.evaluation.reasoning, ["reason 1", "reason 2"])
        self.assertEqual(result.evaluation.recommendations, ["recommendation 1"])

    def test_valid_json_optional_fields_default(self):
        result = self.validator.validate(json.dumps({
            "summary": "x", "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE", "confidence": 0.5,
            "reasoning": ["r"], "recommendations": ["r"],
            "urgency": {"tier": "P2", "page_now": False, "status": "TERMINATED", "reasoning": "test"},
        }))
        self.assertTrue(result.valid)
        self.assertEqual(result.evaluation.failure_modes, ["NONE_DETECTED"])
        self.assertEqual(result.evaluation.suspected_root_cause, "")
        self.assertEqual(result.evaluation.suspected_components, [])

    def test_malformed_json(self):
        result = self.validator.validate("not json")
        self.assertFalse(result.valid)
        self.assertIsNone(result.evaluation)
        self.assertIn("Malformed JSON", result.errors[0])

    def test_not_a_dict(self):
        result = self.validator.validate('["list", "not", "dict"]')
        self.assertFalse(result.valid)
        self.assertIn("Expected JSON object", result.errors[0])

    def test_all_fields_missing(self):
        result = self.validator.validate("{}")
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 7)

    def test_invalid_classification(self):
        result = self.validator.validate(json.dumps({
            "summary": "x", "classification": "BAD_VALUE",
            "recoverability": "RECOVERABLE", "confidence": 0.5,
            "reasoning": ["r"], "recommendations": ["r"],
            "urgency": {"tier": "DEFER", "page_now": False, "status": "TERMINATED", "reasoning": "test"},
        }))
        self.assertFalse(result.valid)
        self.assertIn("Invalid classification", result.errors[0])

    def test_invalid_recoverability(self):
        result = self.validator.validate(json.dumps({
            "summary": "x", "classification": "REAL_INCIDENT",
            "recoverability": "MAYBE", "confidence": 0.5,
            "reasoning": ["r"], "recommendations": ["r"],
            "urgency": {"tier": "DEFER", "page_now": False, "status": "TERMINATED", "reasoning": "test"},
        }))
        self.assertFalse(result.valid)
        self.assertIn("Invalid recoverability", result.errors[0])

    def test_confidence_not_a_number(self):
        result = self.validator.validate(json.dumps({
            "summary": "x", "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE", "confidence": "high",
            "reasoning": ["r"], "recommendations": ["r"],
            "urgency": {"tier": "DEFER", "page_now": False, "status": "TERMINATED", "reasoning": "test"},
        }))
        self.assertFalse(result.valid)
        self.assertIn("confidence must be a number", result.errors[0])

    def test_empty_reasoning(self):
        result = self.validator.validate(json.dumps({
            "summary": "x", "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE", "confidence": 0.5,
            "reasoning": [], "recommendations": ["r"],
            "urgency": {"tier": "DEFER", "page_now": False, "status": "TERMINATED", "reasoning": "test"},
        }))
        self.assertFalse(result.valid)
        self.assertIn("non-empty list", result.errors[0])

    def test_invalid_failure_mode(self):
        result = self.validator.validate(json.dumps({
            "summary": "x", "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE", "confidence": 0.5,
            "failure_modes": ["BAD_MODE"],
            "reasoning": ["r"], "recommendations": ["r"],
            "urgency": {"tier": "DEFER", "page_now": False, "status": "TERMINATED", "reasoning": "test"},
        }))
        self.assertFalse(result.valid)
        self.assertIn("Invalid failure_mode", result.errors[0])

    def test_all_valid_classifications(self):
        for c in ("REAL_INCIDENT", "FALSE_POSITIVE", "INSUFFICIENT_EVIDENCE"):
            tier = "P2" if c == "REAL_INCIDENT" else "DEFER"
            with self.subTest(classification=c):
                result = self.validator.validate(json.dumps({
                    "summary": "x", "classification": c,
                    "recoverability": "RECOVERABLE", "confidence": 0.5,
                    "reasoning": ["r"], "recommendations": ["r"],
                    "urgency": {"tier": tier, "page_now": False, "status": "TERMINATED", "reasoning": "test"},
                }))
                self.assertTrue(result.valid, f"failed for {c}")

    def test_all_valid_failure_modes(self):
        for fm in ("HALLUCINATION", "SILENT_CONTEXT_OVERFLOW", "STALE_CONTEXT",
                   "REASONING_DRIFT", "TOOL_CALL_ANOMALY", "HANDOFF_FAILURE",
                   "TOKEN_BUDGET_SILENT_FAILURE", "LOOPING", "NONE_DETECTED"):
            with self.subTest(failure_mode=fm):
                result = self.validator.validate(json.dumps({
                    "summary": "x", "classification": "REAL_INCIDENT",
                    "recoverability": "RECOVERABLE", "confidence": 0.5,
                    "failure_modes": [fm],
                    "reasoning": ["r"], "recommendations": ["r"],
                    "urgency": {"tier": "P2", "page_now": False, "status": "TERMINATED", "reasoning": "test"},
                }))
                self.assertTrue(result.valid, f"failed for {fm}")


# ─── Scorer Tests ────────────────────────────────────────────────────────

class ConfidenceScorerTest(unittest.TestCase):
    def setUp(self):
        self.scorer = ConfidenceScorer()

    def _make_context(self, **kwargs):
        defaults = dict(
            incident_id="t", fingerprint="f", title="t", severity="SUSPICIOUS",
            labels=["HIGH_LATENCY"], occurrence=1, trace_id="t",
            execution_id="e", first_scene="s1", last_scene="s2",
        )
        defaults.update(kwargs)
        return EvaluationContext(**defaults)

    def _make_eval(self, classification="REAL_INCIDENT", confidence=0.8,
                   recoverability="RECOVERABLE", reasoning=("r1",),
                   recommendations=("r1",)):
        tier = "P2" if classification == "REAL_INCIDENT" else "DEFER"
        return Evaluation(
            summary="t", classification=classification,
            recoverability=recoverability, confidence=confidence,
            reasoning=list(reasoning), recommendations=list(recommendations),
            urgency={"tier": tier, "page_now": False, "status": "TERMINATED", "reasoning": "test"},
        )

    def test_real_incident_match_bonus(self):
        ctx = self._make_context(labels=["HIGH_LATENCY"])
        ev = self._make_eval(classification="REAL_INCIDENT", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.9)

    def test_false_positive_match_bonus(self):
        ctx = self._make_context(labels=["TRANSIENT_ERROR"])
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.85)

    def test_real_incident_positive_label_penalty(self):
        ctx = self._make_context(labels=["TRANSIENT_ERROR"])
        ev = self._make_eval(classification="REAL_INCIDENT", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.65)

    def test_false_positive_real_label_penalty(self):
        ctx = self._make_context(labels=["HIGH_LATENCY"])
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.6)

    def test_high_occurrence_bonus(self):
        ctx = self._make_context(labels=[], occurrence=5)
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.85)

    def test_missing_scenes_penalty(self):
        ctx = self._make_context(labels=[], first_scene="", last_scene="")
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.7)

    def test_insufficient_evidence_cap(self):
        ctx = self._make_context()
        ev = self._make_eval(classification="INSUFFICIENT_EVIDENCE", confidence=0.8)
        self.assertLessEqual(self.scorer.score(0.8, ctx, ev), 0.5)

    def test_score_never_exceeds_one(self):
        ctx = self._make_context(labels=["HIGH_LATENCY", "CRASH_LOOP"],
                                first_scene="a", last_scene="b")
        ev = self._make_eval(classification="REAL_INCIDENT", confidence=0.95)
        self.assertLessEqual(self.scorer.score(0.95, ctx, ev), 1.0)

    def test_score_never_below_zero(self):
        ctx = self._make_context(labels=["HIGH_LATENCY"])
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.1)
        self.assertGreaterEqual(self.scorer.score(0.1, ctx, ev), 0.0)

    def test_no_adjustments(self):
        ctx = self._make_context(labels=[], occurrence=1)
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.5)
        self.assertEqual(self.scorer.score(0.5, ctx, ev), 0.5)

    def test_real_and_positive_conflict(self):
        ctx = self._make_context(labels=["HIGH_LATENCY", "TRANSIENT_ERROR"])
        ev = self._make_eval(classification="REAL_INCIDENT", confidence=0.8)
        score = self.scorer.score(0.8, ctx, ev)
        has_real = bool(set(ctx.labels) & REAL_LABELS)
        has_positive = bool(set(ctx.labels) & POSITIVE_LABELS)
        self.assertTrue(has_real)
        self.assertTrue(has_positive)
        self.assertEqual(score, 0.75)

    def test_failed_tool_calls_boost_real_incident(self):
        tel = TelemetrySummary(failed_tool_calls=3, retry_count=2)
        ctx = self._make_context(labels=["HIGH_LATENCY"])
        ctx.telemetry = tel
        ctx.agent_steps = []
        ev = self._make_eval(classification="REAL_INCIDENT", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.95)

    def test_failed_tool_calls_penalty_false_positive(self):
        tel = TelemetrySummary(failed_tool_calls=2, tool_call_count=5)
        ctx = self._make_context(labels=[], occurrence=1)
        ctx.telemetry = tel
        ctx.agent_steps = []
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.7)

    def test_high_retry_count_bonus(self):
        tel = TelemetrySummary(retry_count=5)
        ctx = self._make_context(labels=[], occurrence=1)
        ctx.telemetry = tel
        ctx.agent_steps = []
        ev = self._make_eval(classification="FALSE_POSITIVE", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.85)

    def test_silent_failure_boost(self):
        ctx = ContextBuilder().build(SAMPLE_INCIDENT_SILENT_FAILURE)
        ctx.labels = []
        ctx.first_scene = "s1"
        ctx.last_scene = "s2"
        ev = self._make_eval(classification="REAL_INCIDENT", confidence=0.8)
        self.assertEqual(self.scorer.score(0.8, ctx, ev), 0.85)


# ─── Agent Integration Tests ─────────────────────────────────────────────

class AgentIntegrationTest(unittest.TestCase):
    def test_agent_returns_full_evaluation(self):
        mock = MockGeminiClient()
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT)
        self.assertIsInstance(result, FullEvaluation)
        self.assertIsInstance(result.evaluation, Evaluation)
        self.assertIsInstance(result.metadata, EvaluationMetadata)
        self.assertEqual(result.metadata.prompt_version, "3.0.0")
        self.assertEqual(result.metadata.model_version, "gemini-3.1-flash-lite")
        self.assertEqual(result.metadata.model_temperature, 0.2)

    def test_agent_rejects_invalid_output(self):
        mock = MockGeminiClient(response="not json")
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT)
        self.assertIsNone(result)

    def test_agent_applies_confidence_adjustment(self):
        mock = MockGeminiClient(response=json.dumps({
            "summary": "x", "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE", "confidence": 0.8,
            "reasoning": ["r"], "recommendations": ["r"],
        }))
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT)
        self.assertEqual(result.evaluation.confidence, 0.9)

    def test_agent_false_positive_blocked(self):
        mock = MockGeminiClient(response=json.dumps({
            "summary": "x", "classification": "FALSE_POSITIVE",
            "recoverability": "RECOVERABLE", "confidence": 0.8,
            "reasoning": ["r"], "recommendations": ["r"],
        }))
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT)
        self.assertEqual(result.evaluation.classification, "FALSE_POSITIVE")
        self.assertLess(result.evaluation.confidence, 0.8)

    def test_agent_rejects_missing_field(self):
        mock = MockGeminiClient(response=json.dumps({
            "summary": "x", "classification": "REAL_INCIDENT",
        }))
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT)
        self.assertIsNone(result)

    def test_agent_includes_urgency(self):
        agent = Agent(gemini_client=MockGeminiClient())
        result = agent.evaluate(SAMPLE_INCIDENT)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.evaluation.urgency)
        self.assertIn(result.evaluation.urgency.tier, {"P0", "P1", "P2", "DEFER"})
        self.assertIsInstance(result.evaluation.urgency.page_now, bool)
        self.assertIn(result.evaluation.urgency.status, {"ACTIVE", "TERMINATED"})
        self.assertTrue(len(result.evaluation.urgency.reasoning) > 10)

    def test_agent_with_trace_data(self):
        mock = MockGeminiClient(response=json.dumps({
            "summary": "Trace analysis completed",
            "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE",
            "confidence": 0.85,
            "failure_modes": ["TOOL_CALL_ANOMALY"],
            "suspected_root_cause": "search tool returned incomplete results",
            "suspected_components": ["search", "llm"],
            "reasoning": ["search tool had high latency"],
            "recommendations": ["optimize search query"],
        }))
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT_WITH_TRACE)
        self.assertIsNotNone(result)
        self.assertEqual(result.evaluation.classification, "REAL_INCIDENT")
        self.assertEqual(result.evaluation.failure_modes, ["TOOL_CALL_ANOMALY"])
        self.assertEqual(result.evaluation.suspected_root_cause,
                         "search tool returned incomplete results")
        self.assertEqual(result.evaluation.suspected_components, ["search", "llm"])


# ─── Pipeline Tests ──────────────────────────────────────────────────────

class FullPipelineTest(unittest.TestCase):
    def test_pipeline_context_to_output(self):
        for label in ("HIGH_LATENCY", "TOKEN_OVERFLOW", "CRASH_LOOP"):
            with self.subTest(label=label):
                incident = dict(SAMPLE_INCIDENT)
                incident["latest_labels"] = [label]
                mock = MockGeminiClient(response=json.dumps({
                    "summary": f"Incident with {label}",
                    "classification": "REAL_INCIDENT",
                    "recoverability": "RECOVERABLE",
                    "confidence": 0.8,
                    "failure_modes": ["NONE_DETECTED"],
                    "suspected_root_cause": "",
                    "suspected_components": [],
                    "reasoning": [f"detected {label}"],
                    "recommendations": [f"fix {label}"],
                }))
                agent = Agent(gemini_client=mock)
                result = agent.evaluate(incident)
                self.assertIsNotNone(result)
                self.assertEqual(result.evaluation.classification, "REAL_INCIDENT")
                self.assertGreaterEqual(result.evaluation.confidence, 0.8)

    def test_pipeline_missing_required_id(self):
        mock = MockGeminiClient()
        agent = Agent(gemini_client=mock)
        with self.assertRaises(KeyError):
            agent.evaluate({"severity": "SUSPICIOUS"})

    def test_pipeline_empty_labels_list(self):
        mock = MockGeminiClient(response=json.dumps({
            "summary": "no labels",
            "classification": "FALSE_POSITIVE",
            "recoverability": "UNKNOWN",
            "confidence": 0.5,
            "failure_modes": ["NONE_DETECTED"],
            "suspected_root_cause": "",
            "suspected_components": [],
            "reasoning": ["no risk labels present"],
            "recommendations": [],
        }))
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(dict(SAMPLE_INCIDENT, latest_labels=[]))
        self.assertIsNotNone(result)
        self.assertEqual(result.evaluation.classification, "FALSE_POSITIVE")

    def test_pipeline_with_trace_data(self):
        mock = MockGeminiClient(response=json.dumps({
            "summary": "Trace analysis",
            "classification": "REAL_INCIDENT",
            "recoverability": "RECOVERABLE",
            "confidence": 0.9,
            "failure_modes": ["TOOL_CALL_ANOMALY"],
            "suspected_root_cause": "tool 1",
            "suspected_components": ["search"],
            "reasoning": ["high latency detected"],
            "recommendations": ["optimize"],
        }))
        agent = Agent(gemini_client=mock)
        result = agent.evaluate(SAMPLE_INCIDENT_WITH_TRACE)
        self.assertIsNotNone(result)
        self.assertEqual(result.evaluation.failure_modes, ["TOOL_CALL_ANOMALY"])
        self.assertIn("search", result.evaluation.suspected_components)


if __name__ == "__main__":
    unittest.main(verbosity=2)
