import ast
import os
import re
import base64
import httpx
from pathlib import Path
from issue_agent.schemas import CodeGraph, CodeGraphNode, CodeGraphEdge


GITHUB_API = "https://api.github.com"
_STDLIB_MODULES = {"os", "sys", "json", "re", "math", "time", "datetime", "collections", "typing",
                   "pathlib", "functools", "itertools", "logging", "hashlib", "base64", "copy",
                   "enum", "dataclasses", "abc", "io", "textwrap", "uuid", "importlib"}


def _ast_parse_code_graph(file_path: str, source: str, repo_files: set[str] | None = None) -> tuple[dict, list]:
    nodes: dict[str, CodeGraphNode] = {file_path: CodeGraphNode(file_path=file_path, kind="file")}
    edges: list[CodeGraphEdge] = []

    for match in re.finditer(r'^(?:from\s+(\S+)\s+)?import\s+(\S+)', source, re.MULTILINE):
        module = match.group(1) or match.group(2)
        target = module.replace(".", "/") + ".py"
        if target[:-3] in _STDLIB_MODULES or target in _STDLIB_MODULES:
            continue
        if repo_files is None or target in repo_files:
            nodes.setdefault(target, CodeGraphNode(file_path=target, kind="file"))
            edges.append(CodeGraphEdge(source=file_path, target=target, relation="imports"))

    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = f"{file_path}::{node.name}"
                nodes[key] = CodeGraphNode(file_path=file_path, kind="function", symbol=node.name)
            elif isinstance(node, ast.ClassDef):
                key = f"{file_path}::{node.name}"
                nodes[key] = CodeGraphNode(file_path=file_path, kind="class", symbol=node.name)
    except SyntaxError:
        for match in re.finditer(r'\bdef\s+(\w+)\s*\(', source):
            key = f"{file_path}::{match.group(1)}"
            nodes[key] = CodeGraphNode(file_path=file_path, kind="function", symbol=match.group(1))

    return nodes, edges


def _search_source_content(path: str, source: str | None, query: str) -> bool:
    if not source:
        return False
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return bool(pattern.search(source))


class GitHubRepo:
    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repo = repo or os.environ.get("DEMO_REPOSITORY", "")
        self._client = httpx.Client(
            base_url=f"{GITHUB_API}/repos/{self.repo}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"},
            timeout=30,
        )

    def _safe_get(self, url: str, params: dict | None = None) -> dict:
        try:
            resp = self._client.get(url, params=params)
            if resp.is_error:
                return {"error": f"GitHub API error {resp.status_code}"}
            return resp.json()
        except httpx.RequestError as e:
            return {"error": f"GitHub request failed: {e}"}

    def search_symbol(self, symbol: str) -> dict:
        data = self._safe_get("/git/trees/HEAD?recursive=1")
        if "error" in data:
            return {"error": data["error"], "matches": []}
        tree = data.get("tree", [])
        truncated = data.get("truncated", False)
        pattern = re.compile(re.escape(symbol), re.IGNORECASE)
        matches = []
        for item in tree:
            if item.get("type") == "blob" and pattern.search(item.get("path", "")):
                path = item["path"]
                content = self.read_file(path)
                if _search_source_content(path, content, symbol):
                    matches.append({"path": path, "matched_in": "content"})
                else:
                    matches.append({"path": path, "matched_in": "filename"})
        result = {"matches": matches}
        if truncated:
            result["truncated"] = True
        return result

    def read_file(self, path: str) -> str | None:
        data = self._safe_get(f"/contents/{path}")
        if "error" in data:
            return None
        if isinstance(data, list):
            return None
        raw = data.get("content", "")
        if not raw:
            return None
        try:
            return base64.b64decode(raw).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None

    def search_files(self, filename: str) -> list[dict]:
        data = self._safe_get(f"{GITHUB_API}/search/code", params={"q": f"filename:{filename} repo:{self.repo}"})
        if "error" in data:
            return []
        return [{"path": item["path"], "name": item["name"]} for item in data.get("items", [])]

    def build_code_graph(self, file_paths: list[str]) -> CodeGraph:
        all_nodes, all_edges = {}, []
        for path in file_paths:
            content = self.read_file(path)
            if content is None:
                continue
            nodes, edges = _ast_parse_code_graph(path, content)
            all_nodes.update(nodes)
            all_edges.extend(edges)
        return CodeGraph(nodes=list(all_nodes.values()), edges=all_edges)

    def create_issue(self, title: str, body: str) -> str | None:
        try:
            resp = self._client.post("/issues", json={"title": title, "body": body})
            if resp.is_error:
                return None
            return resp.json().get("html_url")
        except httpx.RequestError:
            return None


class LocalRepo:
    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or os.environ.get("LOCAL_REPO_PATH", ".")).resolve()

    def _resolve_path(self, path: str) -> Path | None:
        candidate = (self.base_path / path).resolve()
        try:
            candidate.relative_to(self.base_path)
        except ValueError:
            return None
        return candidate

    def search_symbol(self, symbol: str) -> dict:
        pattern = re.compile(re.escape(symbol), re.IGNORECASE)
        matches = []
        for f in self.base_path.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(self.base_path)
            if pattern.search(str(rel)):
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if _search_source_content(str(rel), content, symbol):
                        matches.append({"path": str(rel), "matched_in": "content"})
                    else:
                        matches.append({"path": str(rel), "matched_in": "filename"})
                except (OSError, ValueError):
                    matches.append({"path": str(rel), "matched_in": "filename"})
        return {"matches": matches}

    def read_file(self, path: str) -> str | None:
        full = self._resolve_path(path)
        if full is None or not full.exists() or not full.is_file():
            return None
        try:
            return full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            return None

    def build_code_graph(self, file_paths: list[str]) -> CodeGraph:
        repo_files = {str(f.relative_to(self.base_path)) for f in self.base_path.rglob("*.py") if f.is_file()}
        all_nodes, all_edges = {}, []
        for path in file_paths:
            content = self.read_file(path)
            if content is None:
                continue
            nodes, edges = _ast_parse_code_graph(path, content, repo_files)
            all_nodes.update(nodes)
            all_edges.extend(edges)
        return CodeGraph(nodes=list(all_nodes.values()), edges=all_edges)

    def create_issue(self, title: str, body: str) -> str | None:
        return None