"""Three live segments were asked for a replication no script could perform.

A registered script names the payload file it reads, and the runtime refuses a
replication whose script does not read the heldout world's bytes. Both rules are
right. Together they mean two worlds can host the same experiment only when they
share a payload filename — and six of the catalog's seven schema families do.
`numeric_table` does not: fisher-iris carries `iris.json`, uci-letters carries
`table.json`. Every live segment bound that pair, so `VERIFY` failed with
"registered script does not read heldout world payload" three runs in a row and
`replication` could never leave `missing`.
"""

import unittest
from pathlib import Path

from farfield.extras.openworld.objective import DIRECTED, directed_separation, score_of, SuccessMetric
from farfield.extras.openworld.quality import compute_quality
from farfield.extras.openworld.worldio import payload_names, replication_compatible
from farfield.extras.world import load_fixture


ROOT = Path(__file__).resolve().parents[2]


class Fixture:
    def __init__(self, wid, schema, files, digest="d"):
        self.id, self.schema, self.files, self.digest = wid, schema, tuple(files), digest


class ReplicationCompatibilityTest(unittest.TestCase):
    def test_two_worlds_sharing_a_payload_name_can_host_one_experiment(self):
        self.assertEqual(replication_compatible(
            Fixture("a", "undirected_graph", ("graph.json", "origin.json"), "d1"),
            Fixture("b", "undirected_graph", ("graph.json",), "d2")), "")

    def test_the_live_pair_is_named_as_incompatible(self):
        reason = replication_compatible(
            Fixture("fisher-iris", "numeric_table", ("iris.json",), "d1"),
            Fixture("uci-letters", "numeric_table", ("table.json", "origin.json"), "d2"))
        self.assertIn("no_shared_payload_filename", reason)

    def test_a_different_schema_is_refused_first(self):
        self.assertEqual(replication_compatible(
            Fixture("a", "numeric_table", ("world.json",), "d1"),
            Fixture("b", "undirected_graph", ("world.json",), "d2")),
            "different_scientific_object_schema")

    def test_the_same_bytes_are_not_a_replication(self):
        self.assertEqual(replication_compatible(
            Fixture("a", "s", ("x.json",), "same"),
            Fixture("b", "s", ("x.json",), "same")), "same_bytes")

    def test_bookkeeping_files_are_not_payload(self):
        self.assertEqual(
            payload_names(Fixture("a", "s", ("origin.json", "manifest.json", "seed.json"))),
            set())

    def test_the_real_catalog_is_mostly_replication_capable(self):
        """Six of seven families share a payload name; only numeric_table does not."""
        catalog = ROOT / "worlds"
        if not catalog.is_dir():
            self.skipTest("catalog not present")
        graphs = [load_fixture(catalog / name)
                  for name in ("zachary-karate", "lusseau-dolphins")
                  if (catalog / name / "manifest.json").is_file()]
        if len(graphs) == 2:
            self.assertEqual(replication_compatible(*graphs), "")
        table = [load_fixture(catalog / name)
                 for name in ("fisher-iris", "uci-letters")
                 if (catalog / name / "manifest.json").is_file()]
        if len(table) == 2:
            self.assertIn("no_shared_payload_filename", replication_compatible(*table))


class QualitySaysImpossibleNotUnattemptedTest(unittest.TestCase):
    """Reporting an impossible replication as "not attempted" invites another try."""

    def _state(self, heldout_files):
        from farfield.extras.openworld.events import make_event
        from farfield.extras.openworld.reducer import apply_events
        from farfield.extras.openworld.state import ScientificState

        probe = {"evidence_id": "E1", "role": "ProbeEvidence", "epistemic": "WORLD",
                 "attested": True, "promotion_ok": True, "execution_status": "ran",
                 "world_id": "W0", "world_digest": "d0", "experiment_digest": "x",
                 "theory_id": "T1", "question_id": "Q1", "outcome": "supports",
                 "sample_size": 500, "claim_consistent": True}
        return apply_events(ScientificState(goal="g"), [
            make_event("ContractSet", {"root_question": "g"}),
            make_event("WorldCreated", {"id": "W1", "world_id": "W1", "digest": "d1",
                                        "schema": "numeric_table", "files": heldout_files,
                                        "research_role": "heldout"}),
            make_event("WorldCreated", {"id": "W0", "world_id": "W0", "digest": "d0",
                                        "schema": "numeric_table", "files": ["iris.json"],
                                        "research_role": "world"}),
            make_event("EvidenceAdded", probe),
        ])

    def test_an_unusable_heldout_is_reported_as_impossible(self):
        row = compute_quality(self._state(["table.json"]))["dimensions"]["replication"]
        self.assertIn("no_heldout_world_can_host", " ".join(row["blocking_reasons"]))
        self.assertIn("ACQUIRE", row["required_next_work"])

    def test_a_usable_heldout_is_still_reported_as_unattempted(self):
        row = compute_quality(self._state(["iris.json"]))["dimensions"]["replication"]
        self.assertIn("no_heldout_replication_attempted", " ".join(row["blocking_reasons"]))
        self.assertIn("VERIFY", row["required_next_work"])


class DirectionalMetricTest(unittest.TestCase):
    """A live frontier stood at -0.177613 from a `weakens` result.

    Raw separation with higher-is-better could not tell a large effect in the
    registered direction from a large effect the other way, so a contradiction
    became the project's best result.
    """

    def test_a_reversal_scores_zero_not_its_magnitude(self):
        self.assertEqual(
            directed_separation({"separation": -0.177613, "verdict": "weakens"}), 0.0)

    def test_a_supporting_result_scores_its_magnitude(self):
        self.assertEqual(
            directed_separation({"separation": 0.85, "verdict": "supports"}), 0.85)

    def test_an_inconclusive_result_scores_zero(self):
        self.assertEqual(
            directed_separation({"separation": 0.002, "verdict": "uninformative"}), 0.0)

    def test_a_missing_or_non_numeric_separation_scores_nothing(self):
        for row in ({"verdict": "supports"}, {"separation": "big", "verdict": "supports"},
                    {"separation": True, "verdict": "supports"}):
            with self.subTest(row=row):
                self.assertIsNone(directed_separation(row))

    def test_the_metric_is_declarable_and_reads_the_directed_value(self):
        metric = SuccessMetric.from_dict(
            {"name": "strength", "source": DIRECTED, "direction": "higher_is_better"})
        self.assertTrue(metric.is_declared)
        row = {"separation": -0.5, "verdict": "weakens", "role": "ProbeEvidence",
               "epistemic": "WORLD", "attested": True, "promotion_ok": True,
               "execution_status": "ran"}
        self.assertEqual(score_of(metric, row), 0.0)

    def test_a_contradiction_can_no_longer_top_the_frontier(self):
        metric = SuccessMetric.from_dict(
            {"name": "s", "source": DIRECTED, "direction": "higher_is_better"})
        base = {"role": "ProbeEvidence", "epistemic": "WORLD", "attested": True,
                "promotion_ok": True, "execution_status": "ran"}
        reversal = score_of(metric, {**base, "separation": -0.9, "verdict": "weakens"})
        support = score_of(metric, {**base, "separation": 0.1, "verdict": "supports"})
        self.assertLess(reversal, support)


if __name__ == "__main__":
    unittest.main()
