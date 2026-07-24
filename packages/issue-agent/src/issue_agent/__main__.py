import json
import sys
import os
import logging
from pydantic import ValidationError
from issue_agent.schemas import IncidentSnapshot
from issue_agent.repository import GitHubRepo, LocalRepo
from issue_agent.agent import run_issue_agent


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
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

    dev_mode = os.environ.get("VOID_DEV_MODE")
    if not dev_mode:
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("DEMO_REPOSITORY")
        if not token:
            logger.error("Production mode requires GITHUB_TOKEN environment variable")
            sys.exit(1)
        if not repo:
            logger.error("Production mode requires DEMO_REPOSITORY environment variable")
            sys.exit(1)

    repo = LocalRepo() if dev_mode else GitHubRepo()
    report = run_issue_agent(snapshot, repo)
    if report:
        print(report.model_dump_json(indent=2))
    else:
        logger.error("Issue agent failed to produce a report")
        sys.exit(1)


if __name__ == "__main__":
    main()