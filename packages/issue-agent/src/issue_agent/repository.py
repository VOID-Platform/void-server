import ast
import os
import re
import base64
import logging
import httpx
from pathlib import Path
from issue_agent.schemas import CodeGraph, CodeGraphNode, CodeGraphEdge

logger = logging.getLogger(__name__)

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
        repo_val = repo or os.environ.get("DEMO_REPOSITORY") or os.environ.get("DEMO_REPOSITRY", "")
        if repo_val.startswith("https://github.com/"):
            repo_val = repo_val[len("https://github.com/"):]
        elif repo_val.startswith("http://github.com/"):
            repo_val = repo_val[len("http://github.com/"):]
        elif repo_val.startswith("github.com/"):
            repo_val = repo_val[len("github.com/"):]
        self.repo = repo_val.strip("/")
        self._client = httpx.Client(
            base_url=f"{GITHUB_API}/repos/{self.repo}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github.v3+json"},
            timeout=30,
        )
        self._file_cache: dict[str, str | None] = {}
        self._search_cache: dict[str, dict] = {}
        self._graph_cache: dict[tuple[str, ...], CodeGraph] = {}

    def _safe_get(self, url: str, params: dict | None = None) -> dict:
        try:
            resp = self._client.get(url, params=params)
            if resp.is_error:
                return {"error": f"GitHub API error {resp.status_code}"}
            return resp.json()
        except httpx.RequestError as e:
            return {"error": f"GitHub request failed: {e}"}

    def search_symbol(self, symbol: str) -> dict:
        if symbol in self._search_cache:
            logger.info("[repo] cache hit search_symbol symbol=%r", symbol)
            return self._search_cache[symbol]

        content_data = self._safe_get(
            f"{GITHUB_API}/search/code",
            params={"q": f"{symbol} repo:{self.repo}"},
        )

        tree_data = self._safe_get("/git/trees/HEAD?recursive=1")

        matches = []
        seen_paths: set[str] = set()
        pattern = re.compile(re.escape(symbol), re.IGNORECASE)

        if "error" not in content_data:
            for item in content_data.get("items", []):
                path = item["path"]
                seen_paths.add(path)
                matches.append({"path": path, "matched_in": "content"})

        if "error" not in tree_data:
            for item in tree_data.get("tree", []):
                if item.get("type") != "blob":
                    continue
                path = item["path"]
                if path in seen_paths:
                    continue
                if pattern.search(path):
                    seen_paths.add(path)
                    matches.append({"path": path, "matched_in": "filename"})

        result = {"matches": matches}
        incomplete = content_data.get("incomplete_results", False) if "error" not in content_data else False
        truncated = tree_data.get("truncated", False) if "error" not in tree_data else False
        if incomplete or truncated:
            result["truncated"] = True

        self._search_cache[symbol] = result
        return result

    def read_file(self, path: str) -> str | None:
        if path in self._file_cache:
            logger.info("[repo] cache hit read_file path=%r", path)
            return self._file_cache[path]

        data = self._safe_get(f"/contents/{path}")
        if "error" in data or isinstance(data, list):
            self._file_cache[path] = None
            return None
        raw = data.get("content", "")
        if not raw:
            self._file_cache[path] = None
            return None
        try:
            content = base64.b64decode(raw).decode("utf-8")
            self._file_cache[path] = content
            return content
        except (UnicodeDecodeError, ValueError):
            self._file_cache[path] = None
            return None

    def search_files(self, filename: str) -> list[dict]:
        data = self._safe_get(f"{GITHUB_API}/search/code", params={"q": f"filename:{filename} repo:{self.repo}"})
        if "error" in data:
            return []
        return [{"path": item["path"], "name": item["name"]} for item in data.get("items", [])]

    def build_code_graph(self, file_paths: list[str]) -> CodeGraph:
        cache_key = tuple(sorted(set(file_paths)))
        if cache_key in self._graph_cache:
            logger.info("[repo] cache hit build_code_graph paths=%s", cache_key)
            return self._graph_cache[cache_key]

        all_nodes, all_edges = {}, []
        for path in file_paths:
            content = self.read_file(path)
            if content is None:
                continue
            nodes, edges = _ast_parse_code_graph(path, content)
            all_nodes.update(nodes)
            all_edges.extend(edges)
        graph = CodeGraph(nodes=list(all_nodes.values()), edges=all_edges)
        self._graph_cache[cache_key] = graph
        return graph

    def create_issue(self, title: str, body: str) -> str | None:
        try:
            resp = self._client.post("/issues", json={"title": title, "body": body})
            if resp.is_error:
                logger.error(f"GitHub API error creating issue ({resp.status_code}): {resp.text}")
                return None
            return resp.json().get("html_url")
        except httpx.RequestError as e:
            logger.error(f"GitHub request error creating issue: {e}")
            return None


class LocalRepo:
    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or os.environ.get("LOCAL_REPO_PATH", ".")).resolve()
        self._file_cache: dict[str, str | None] = {}
        self._search_cache: dict[str, dict] = {}
        self._graph_cache: dict[tuple[str, ...], CodeGraph] = {}

    def _resolve_path(self, path: str) -> Path | None:
        candidate = (self.base_path / path).resolve()
        try:
            candidate.relative_to(self.base_path)
        except ValueError:
            return None
        return candidate

    def search_symbol(self, symbol: str) -> dict:
        if symbol in self._search_cache:
            return self._search_cache[symbol]

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
        res = {"matches": matches}
        self._search_cache[symbol] = res
        return res

    def read_file(self, path: str) -> str | None:
        if path in self._file_cache:
            return self._file_cache[path]

        full = self._resolve_path(path)
        if full is None or not full.exists() or not full.is_file():
            self._file_cache[path] = None
            return None
        try:
            content = full.read_text(encoding="utf-8")
            self._file_cache[path] = content
            return content
        except (UnicodeDecodeError, ValueError):
            self._file_cache[path] = None
            return None

    def build_code_graph(self, file_paths: list[str]) -> CodeGraph:
        cache_key = tuple(sorted(set(file_paths)))
        if cache_key in self._graph_cache:
            return self._graph_cache[cache_key]

        repo_files = {str(f.relative_to(self.base_path)) for f in self.base_path.rglob("*.py") if f.is_file()}
        all_nodes, all_edges = {}, []
        for path in file_paths:
            content = self.read_file(path)
            if content is None:
                continue
            nodes, edges = _ast_parse_code_graph(path, content, repo_files)
            all_nodes.update(nodes)
            all_edges.extend(edges)
        graph = CodeGraph(nodes=list(all_nodes.values()), edges=all_edges)
        self._graph_cache[cache_key] = graph
        return graph

    def create_issue(self, title: str, body: str) -> str | None:
        return None