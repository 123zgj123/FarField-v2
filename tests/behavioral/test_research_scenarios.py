"""Capability-level behavioural scenarios, run as regression tests.

These grade decisions, not functions: given a research situation, what does the
controller do next? They are deterministic and offline. Passing them is not
evidence that FarField does good science — only that it does not do these
specific stupid things.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld.benchmark import SCENARIOS, run_scenario


class ResearchScenarioTest(unittest.TestCase):
    def test_every_scenario_behaves_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            for scenario in SCENARIOS:
                with self.subTest(scenario=scenario.name, title=scenario.title):
                    row = run_scenario(scenario, Path(tmp))
                    self.assertTrue(
                        row["passed"],
                        f"{scenario.name} ({scenario.title}) chose {row['chosen']!r}: "
                        + "; ".join(row["failures"]),
                    )

    def test_every_declared_capability_is_covered(self):
        capabilities = {scenario.capability for scenario in SCENARIOS}
        self.assertEqual(
            capabilities,
            {"research_judgment", "research_adaptation", "goal_maintenance",
             "project_backtracking", "resource_awareness", "evidence_grounding"},
        )


if __name__ == "__main__":
    unittest.main()
