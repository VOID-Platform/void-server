import unittest
import json
import os
from issue_agent.schemas import IncidentSnapshot
from issue_agent.evidence import extract_evidence


class TestExtractEvidence(unittest.TestCase):
    def setUp(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "scenarios", "tool_timeout", "incident.json")
        with open(fixture_path) as f:
            data = json.load(f)
        self.snapshot = IncidentSnapshot.model_validate(data)

    def test_extract_evidence_from_tool_timeout(self):
        evidence = extract_evidence(self.snapshot)
        self.assertGreater(len(evidence), 0)
        self.assertIn("TOOL_TIMEOUT", [e.failure_mode for e in evidence])
        for e in evidence:
            self.assertGreaterEqual(e.confidence, 0.0)
            self.assertLessEqual(e.confidence, 1.0)

    def test_extract_evidence_includes_failed_tool_calls(self):
        evidence = extract_evidence(self.snapshot)
        for e in evidence:
            if e.failure_mode == "TOOL_TIMEOUT":
                self.assertTrue(
                    any("search_documents" in line for line in e.supporting_trace),
                )


class TestEvidenceAcrossScenarios(unittest.TestCase):
    def _load_scenario(self, name):
        fixture_path = os.path.join(os.path.dirname(__file__), "scenarios", name, "incident.json")
        with open(fixture_path) as f:
            data = json.load(f)
        return IncidentSnapshot.model_validate(data)

    def test_planner_bug_evidence(self):
        snapshot = self._load_scenario("planner_bug")
        evidence = extract_evidence(snapshot)
        self.assertGreater(len(evidence), 0)
        self.assertIn("INEFFICIENT_PLANNING", [e.failure_mode for e in evidence])

    def test_handoff_failure_evidence(self):
        snapshot = self._load_scenario("handoff_failure")
        evidence = extract_evidence(snapshot)
        self.assertGreater(len(evidence), 0)
        self.assertIn("HANDOFF_CONTEXT_LOSS", [e.failure_mode for e in evidence])

    def test_context_overflow_evidence(self):
        snapshot = self._load_scenario("context_overflow")
        evidence = extract_evidence(snapshot)
        self.assertGreater(len(evidence), 0)
        self.assertIn("SILENT_CONTEXT_OVERFLOW", [e.failure_mode for e in evidence])

    def test_tool_anomaly_evidence(self):
        snapshot = self._load_scenario("tool_call_anomaly")
        evidence = extract_evidence(snapshot)
        self.assertGreater(len(evidence), 0)
        self.assertIn("PARTIAL_TOOL_SUCCESS", [e.failure_mode for e in evidence])


if __name__ == "__main__":
    unittest.main()