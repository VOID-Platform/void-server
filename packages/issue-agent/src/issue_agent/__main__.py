import json
import sys
import os
import logging
from issue_agent.schemas import IncidentSnapshot
from issue_agent.repository import GitHubRepo, LocalRepo
from issue_agent.agent import run_issue_agent


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    raw = json.loads(sys.stdin.read())
    snapshot = IncidentSnapshot.model_validate(raw)
    repo = LocalRepo() if os.environ.get("VOID_DEV_MODE") else GitHubRepo()
    report = run_issue_agent(snapshot, repo)
    if report:
        print(report.model_dump_json(indent=2))
    else:
        logger.error("Issue agent failed to produce a report")
        sys.exit(1)


if __name__ == "__main__":
    main()