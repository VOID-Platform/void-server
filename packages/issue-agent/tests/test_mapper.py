import unittest
import os
import sys

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_helpers import build_snapshot, validate_report, load_json


_HERE = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))


class TestMapper(unittest.TestCase):
    def test_context_overflow_maps_correctly(self):
        path = os.path.join(_PROJECT_ROOT, "evaluation_dataset", "incidents", "context-overflow", "incident.json")
        incident = load_json(path)
        evaluator = {
            "evaluation": {
                "failure_modes": ["HALLUCINATION", "SILENT_CONTEXT_OVERFLOW"],
                "confidence": 1.0,
                "suspected_root_cause": "context overflow",
                "classification": "REAL_INCIDENT",
            }
        }
        snapshot = build_snapshot(incident, evaluator)
        self.assertEqual(snapshot.incident_id, "ctx-001")
        self.assertEqual(len(snapshot.execution_trace.agent_steps), 3)
        self.assertEqual(len(snapshot.execution_trace.agent_steps[0].tool_calls), 1)
        self.assertEqual(snapshot.execution_trace.agent_steps[0].tool_calls[0].name, "retrieve_docs")
        self.assertIn("SILENT_CONTEXT_OVERFLOW", snapshot.evaluation.failure_modes)

    def test_insufficient_evidence_maps_correctly(self):
        path = os.path.join(_PROJECT_ROOT, "evaluation_dataset", "incidents", "insufficient-evidence", "incident.json")
        incident = load_json(path)
        evaluator = {
            "evaluation": {
                "failure_modes": [],
                "confidence": 0.5,
                "suspected_root_cause": "missing trace data",
                "classification": "INSUFFICIENT_EVIDENCE",
            }
        }
        snapshot = build_snapshot(incident, evaluator)
        self.assertEqual(snapshot.incident_id, "ie-001")

    def test_validate_real_incident_pass(self):
        expected = {
            "classification": "REAL_INCIDENT",
            "root_cause_must_contain": ["context"],
            "confidence_min": 0.5,
        }
        report = type("R", (), {
            "root_cause": "Context overflow detected", "summary": "test",
            "suspected_components": ["context_manager"],
            "suggested_investigation": ["prune context"],
            "suggested_tests": ["regression"],
            "evidence": ["tool call failed"],
            "confidence": 0.9,
            "suggested_fix": "",
        })()
        errors = validate_report(report, expected)
        self.assertEqual(errors, [])

    def test_validate_real_incident_fail(self):
        expected = {
            "classification": "REAL_INCIDENT",
            "root_cause_must_contain": ["context"],
            "confidence_min": 0.9,
        }
        report = type("R", (), {
            "root_cause": "something else", "summary": "test",
            "suspected_components": [],
            "suggested_investigation": [],
            "suggested_tests": [],
            "evidence": ["tool call failed"],
            "confidence": 0.5,
            "suggested_fix": "",
        })()
        errors = validate_report(report, expected)
        self.assertGreater(len(errors), 0)

    def test_validate_insufficient_evidence_pass(self):
        expected = {
            "classification": "INSUFFICIENT_EVIDENCE",
            "must_not_suggest_fix": True,
            "must_not_identify_root_cause": True,
            "confidence_max": 0.6,
            "summary_must_contain": ["cannot", "trace"],
        }
        report = type("R", (), {
            "root_cause": "missing trace data", "summary": "cannot investigate without trace data",
            "suspected_components": [],
            "suggested_investigation": [],
            "suggested_tests": [],
            "evidence": [],
            "confidence": 0.3,
            "suggested_fix": "",
        })()
        errors = validate_report(report, expected)
        self.assertEqual(errors, [])

    def test_validate_insufficient_evidence_fails_on_fix(self):
        expected = {
            "classification": "INSUFFICIENT_EVIDENCE",
            "must_not_suggest_fix": True,
        }
        report = type("R", (), {
            "root_cause": "", "summary": "",
            "suspected_components": [],
            "suggested_investigation": [],
            "suggested_tests": [],
            "evidence": [],
            "confidence": 0.3,
            "suggested_fix": "Implement exponential backoff",
        })()
        errors = validate_report(report, expected)
        self.assertGreater(len(errors), 0)


if __name__ == "__main__":
    unittest.main()