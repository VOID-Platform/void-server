import unittest
from pydantic import ValidationError
from issue_agent.schemas import (
    IncidentSnapshot, Evidence, EngineeringReport,
    CodeGraph, CodeGraphNode, CodeGraphEdge,
    GitHubIssueInput,
)


class TestSchemas(unittest.TestCase):
    def test_incident_snapshot_defaults(self):
        snapshot = IncidentSnapshot(
            incident_id="test_001",
            execution_trace={"agent_steps": []},
            evaluation={
                "failure_modes": ["TEST"],
                "confidence": 0.9,
                "reasoning": "test",
            },
        )
        self.assertEqual(snapshot.incident_id, "test_001")
        self.assertEqual(snapshot.evaluation.confidence, 0.9)

    def test_evidence_confidence_bounds(self):
        with self.assertRaises(ValidationError):
            Evidence(failure_mode="X", summary="test", confidence=1.5)

    def test_engineering_report_defaults(self):
        report = EngineeringReport(
            summary="test",
            root_cause="test",
            suggested_fix="test fix",
            confidence=0.85,
        )
        self.assertEqual(report.suspected_components, [])

    def test_code_graph_empty(self):
        graph = CodeGraph()
        self.assertEqual(len(graph.nodes), 0)
        self.assertEqual(len(graph.edges), 0)

    def test_code_graph_with_nodes(self):
        node = CodeGraphNode(file_path="test.py", kind="file")
        graph = CodeGraph(nodes=[node])
        self.assertEqual(len(graph.nodes), 1)

    def test_github_issue_input(self):
        issue = GitHubIssueInput(owner="o", repo="r", title="t", body="b")
        self.assertEqual(issue.title, "t")

    def test_engineering_report_confidence_bounds(self):
        with self.assertRaises(ValidationError):
            EngineeringReport(summary="x", root_cause="x", suggested_fix="x", confidence=-0.1)


if __name__ == "__main__":
    unittest.main()