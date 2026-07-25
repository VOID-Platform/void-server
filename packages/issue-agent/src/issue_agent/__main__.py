import json
import sys
import os
import logging
from pathlib import Path
from pydantic import ValidationError
from issue_agent.schemas import IncidentSnapshot
from issue_agent.repository import GitHubRepo, LocalRepo
from issue_agent.agent import run_issue_agent, create_github_issue_from_report


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent.parent
_DOT_ENV = _PROJECT_ROOT / ".env"


def _load_dotenv():
    if not _DOT_ENV.exists():
        return
    for line in _DOT_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def main():
    _load_dotenv()
    try:
        raw = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON input: {e}")
        sys.exit(1)

    try:
        snapshot = IncidentSnapshot.model_validate(raw)
    except ValidationError as e:
        logger.error(f"Invalid incident snapshot: {e}")
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("DEMO_REPOSITORY")

    if token and repo_name:
        repo = GitHubRepo(token=token, repo=repo_name)
    else:
        repo = LocalRepo()

    report = run_issue_agent(snapshot, repo)
    if report:
        if isinstance(repo, GitHubRepo):
            issue_url = create_github_issue_from_report(repo, report, snapshot.incident_id)
            if issue_url:
                logger.info(f"Created GitHub issue: {issue_url}")
                print(f"GitHub issue created: {issue_url}")
            else:
                logger.error("Failed to create GitHub issue")
                sys.exit(1)
        else:
            print(report.model_dump_json(indent=2))
    else:
        logger.error("Issue agent failed to produce a report")
        sys.exit(1)


if __name__ == "__main__":
    main()