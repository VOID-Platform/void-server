import os
import re
import httpx
from pathlib import Path
from issue_agent.schemas import CodeGraph, CodeGraphNode, CodeGraphEdge


GITHUB_API = "https://api.github.com"


def _parse_code_graph(file_path: str, content: str) -> tuple[dict, list]:
    nodes = {file_path: CodeGraphNode(file_path=file_path, kind="file")}
    edges = []
    for match in re.finditer(r'^(?:from\s+(\S+)\s+)?import\s+(\S+)', content, re.MULTILINE):
        module = match.group(1) or match.group(2)
        target = module.replace(".", "/") + ".py"
        edges.append(CodeGraphEdge(source=file_path, target=target, relation="imports"))
        nodes.setdefault(target, CodeGraphNode(file_path=target, kind="file"))
    for match in re.finditer(r'\bdef\s+(\w+)\s*\(', content):
        key = f"{file_path}::{match.group(1)}"
        nodes[key] = CodeGraphNode(file_path=file_path, kind="function", symbol=match.group(1))
    return nodes, edges


class GitHubRepo:
    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repo = repo or os.environ.get("DEMO_REPOSITORY", "")
        self._client = httpx.Client(
            base_url=f"{GITHUB_API}/repos/{self.repo}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"},
            timeout=30,
        )

    def search_code(self, query: str) -> list[dict]:
        resp = self._client.get("/contents/", params={"q": query})
        if resp.is_error:
            return []
        data = resp.json()
        if isinstance(data, list):
            return [{"path": item["path"], "type": item["type"], "name": item["name"]} for item in data]
        return []

    def search_symbol(self, symbol: str) -> list[dict]:
        resp = self._client.get("/git/trees/HEAD?recursive=1")
        if resp.is_error:
            return []
        tree = resp.json().get("tree", [])
        pattern = re.compile(re.escape(symbol), re.IGNORECASE)
        return [{"path": item["path"], "sha": item["sha"]} for item in tree
                if item["type"] == "blob" and pattern.search(item["path"])]

    def read_file(self, path: str) -> str | None:
        resp = self._client.get(f"/contents/{path}")
        if resp.is_error:
            return None
        data = resp.json()
        import base64
        content = data.get("content", "")
        return base64.b64decode(content).decode("utf-8") if content else None

    def search_files(self, filename: str) -> list[dict]:
        resp = self._client.get(f"/search/code?q={filename}+repo:{self.repo}")
        if resp.is_error:
            return []
        data = resp.json()
        return [{"path": item["path"], "name": item["name"]} for item in data.get("items", [])]

    def build_code_graph(self, file_paths: list[str]) -> CodeGraph:
        all_nodes, all_edges = {}, []
        for path in file_paths:
            content = self.read_file(path)
            if content is None:
                continue
            nodes, edges = _parse_code_graph(path, content)
            all_nodes.update(nodes)
            all_edges.extend(edges)
        return CodeGraph(nodes=list(all_nodes.values()), edges=all_edges)

    def create_issue(self, title: str, body: str) -> str | None:
        resp = self._client.post("/issues", json={"title": title, "body": body})
        if resp.is_error:
            return None
        return resp.json().get("html_url")


class LocalRepo:
    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or os.environ.get("LOCAL_REPO_PATH", "."))

    def search_symbol(self, symbol: str) -> list[dict]:
        pattern = re.compile(re.escape(symbol), re.IGNORECASE)
        results = []
        for f in self.base_path.rglob("*"):
            if f.is_file() and pattern.search(f.name):
                results.append({"path": str(f.relative_to(self.base_path)), "sha": ""})
        return results

    def read_file(self, path: str) -> str | None:
        full = self.base_path / path
        if not full.exists() or not full.is_file():
            return None
        try:
            return full.read_text()
        except (UnicodeDecodeError, ValueError):
            return None

    def build_code_graph(self, file_paths: list[str]) -> CodeGraph:
        all_nodes, all_edges = {}, []
        for path in file_paths:
            content = self.read_file(path)
            if content is None:
                continue
            nodes, edges = _parse_code_graph(path, content)
            all_nodes.update(nodes)
            all_edges.extend(edges)
        return CodeGraph(nodes=list(all_nodes.values()), edges=all_edges)

    def create_issue(self, title: str, body: str) -> str | None:
        return None