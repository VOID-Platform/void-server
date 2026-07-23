import json
import os
import sys

_HERE = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
_DOT_ENV = os.path.join(_PROJECT_ROOT, ".env")


def _load_dotenv():
    if not os.path.exists(_DOT_ENV):
        return
    with open(_DOT_ENV) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = val


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m evaluator")
        print("  Reads incident JSON from stdin, outputs evaluation JSON to stdout.")
        print("  Requires GOOGLE_API_KEY in environment or repo-root .env")
        sys.exit(0)

    _load_dotenv()

    try:
        incident_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid input JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    from .agent import Agent

    agent = Agent()
    result = agent.evaluate(incident_data)

    if result is None:
        print(json.dumps({"error": "Evaluation failed (validation rejected output)"}))
        sys.exit(1)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
