import unittest
import os
from unittest.mock import patch, MagicMock, PropertyMock
from issue_agent.repository import GitHubRepo


class TestGitHubRepo(unittest.TestCase):
    def setUp(self):
        self.repo = GitHubRepo(token="test_token", repo="test_owner/test_repo")
        self.repo._client = MagicMock()

    def test_search_symbol_returns_matching_files(self):
        mock_resp = MagicMock()
        mock_resp.is_error = False
        mock_resp.json.return_value = {
            "tree": [
                {"path": "src/tool_executor.py", "type": "blob", "sha": "abc"},
                {"path": "src/planner.py", "type": "blob", "sha": "def"},
                {"path": "README.md", "type": "blob", "sha": "ghi"},
            ]
        }
        self.repo._client.get.return_value = mock_resp
        # Mock read_file to return content containing "executor"
        self.repo.read_file = MagicMock(return_value="def executor(): pass")
        results = self.repo.search_symbol("executor")
        self.assertEqual(results["matches"][0]["path"], "src/tool_executor.py")

    def test_search_symbol_empty_on_error(self):
        mock_resp = MagicMock()
        mock_resp.is_error = True
        mock_resp.status_code = 500
        self.repo._client.get.return_value = mock_resp
        results = self.repo.search_symbol("anything")
        self.assertEqual(results["matches"], [])

    def test_build_code_graph_empty_file_list(self):
        graph = self.repo.build_code_graph([])
        self.assertEqual(len(graph.nodes), 0)

    def test_create_issue_returns_url(self):
        mock_resp = MagicMock()
        mock_resp.is_error = False
        mock_resp.json.return_value = {"html_url": "https://github.com/test_owner/test_repo/issues/1"}
        self.repo._client.post.return_value = mock_resp
        url = self.repo.create_issue("test title", "test body")
        self.assertEqual(url, "https://github.com/test_owner/test_repo/issues/1")

    def test_create_issue_returns_none_on_error(self):
        mock_resp = MagicMock()
        mock_resp.is_error = True
        self.repo._client.post.return_value = mock_resp
        url = self.repo.create_issue("test title", "test body")
        self.assertIsNone(url)


class TestGitHubRepoInitialization(unittest.TestCase):
    def test_defaults_from_env(self):
        with unittest.mock.patch.dict(os.environ, {"GITHUB_TOKEN": "env_token", "DEMO_REPOSITORY": "env_owner/env_repo"}, clear=True):
            repo = GitHubRepo()
            self.assertEqual(repo.token, "env_token")
            self.assertEqual(repo.repo, "env_owner/env_repo")

    def test_explicit_values_override_env(self):
        repo = GitHubRepo(token="explicit", repo="explicit/repo")
        self.assertEqual(repo.token, "explicit")
        self.assertEqual(repo.repo, "explicit/repo")


if __name__ == "__main__":
    unittest.main()