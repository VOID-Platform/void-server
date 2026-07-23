"""
Live Gemini API Integration Test.

Run:
    cd packages/evaluator
    PYTHONPATH=src .venv/bin/python3 -m unittest tests/test_live_gemini.py -v

Requires GOOGLE_API_KEY set in environment or in project root .env
"""

import json
import os
import unittest

from evaluator.agent import Agent
from evaluator.schemas import Evaluation, FullEvaluation


# Load .env if present and GOOGLE_API_KEY not set
if not os.getenv("GOOGLE_API_KEY"):
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")


@unittest.skipUnless(os.getenv("GOOGLE_API_KEY"), "GOOGLE_API_KEY environment variable not set")
class LiveGeminiTest(unittest.TestCase):
    def test_live_gemini_evaluation(self):
        agent = Agent()
        dataset_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "evaluation_dataset", "incidents", "example",
        )
        incident_path = os.path.join(dataset_dir, "incident.json")
        
        with open(incident_path) as f:
            incident = json.load(f)

        try:
            result = agent.evaluate(incident)
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                self.skipTest(f"Gemini API quota exceeded: {e}")
            raise e

        self.assertIsNotNone(result, "Live Gemini evaluation returned None")
        self.assertIsInstance(result, FullEvaluation)
        self.assertIsInstance(result.evaluation, Evaluation)
        self.assertIn(
            result.evaluation.classification,
            {"REAL_INCIDENT", "FALSE_POSITIVE", "INSUFFICIENT_EVIDENCE"},
        )

        self.assertIsNotNone(result.evaluation.urgency)
        self.assertIn(result.evaluation.urgency.tier, {"P0", "P1", "P2", "DEFER"})
        self.assertIsInstance(result.evaluation.urgency.page_now, bool)
        self.assertIn(result.evaluation.urgency.status, {"ACTIVE", "TERMINATED"})
        self.assertTrue(len(result.evaluation.urgency.reasoning) > 10)

        if result.evaluation.classification in {"FALSE_POSITIVE", "INSUFFICIENT_EVIDENCE"}:
            self.assertEqual(result.evaluation.urgency.tier, "DEFER")
            self.assertFalse(result.evaluation.urgency.page_now)


if __name__ == "__main__":
    unittest.main(verbosity=2)
