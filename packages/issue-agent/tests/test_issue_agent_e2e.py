import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_helpers import run_scenario, SCENARIOS, _load_dotenv

_load_dotenv()


class TestIssueAgentE2E(unittest.TestCase):
    pass


def _generate_tests():
    has_api = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    for scenario in SCENARIOS:
        def _test(self, s=scenario):
            result = run_scenario(s)
            if result["errors"]:
                raise AssertionError(f"{s}: {'; '.join(result['errors'][:5])}")
        if not has_api:
            _test = unittest.skip("GEMINI_API_KEY not set (set in .env or environment)")(_test)
        setattr(TestIssueAgentE2E, f"test_{scenario.replace('-', '_')}", _test)


_generate_tests()


if __name__ == "__main__":
    unittest.main()