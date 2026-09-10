"""A research agent that cannot obtain its object cannot answer the question.

ACQUIRE previously supported exactly one gap and failed closed on everything
else, while attested worlds sat on disk the controller had no way to bind. The
fix must unblock that without opening a hole in the evidence boundary: a recipe
may bind already-attested bytes or derive from an attested parent, and it may
never fetch bytes a model chose.
"""

import json
import tempfile
import unittest
from pathlib import Path

from farfield.extras.freeze import freeze_world
from farfield.extras.openworld import OpenWorld
from farfield.extras.openworld.actions import SPECS, ActionInstance
from farfield.extras.openworld.recipes import (
    CATALOG_BINDING,
    DERIVED,
    available_recipes,
    catalog_worlds,
    match_catalog_world,
    resolve_recipe,
)


def _catalog(root: Path) -> Path:
    """Two genuinely attested worlds with different schemas."""
    catalog = root / "catalog"
    table = root / "table.csv"
    table.write_text("key,value\na,1\nb,2\n", encoding="utf-8")
    freeze_world(world_id="tbl-world", schema="numeric_table", slice_rule="first_rows:2",
                 catalog=catalog, url="https://example.invalid/t.csv", source_file=table,
                 domains=("table", "numeric"))
    graph = root / "graph.txt"
    graph.write_text("1 2\n2 3\n", encoding="utf-8")
    freeze_world(world_id="gph-world", schema="undirected_graph", slice_rule="first_edges:2",
                 catalog=catalog, url="https://example.invalid/g.txt", source_file=graph,
                 domains=("graph", "network"))
    return catalog


class RecipeRegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.catalog = _catalog(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_only_attested_worlds_are_offered(self):
        junk = self.catalog / "not-a-world"
        junk.mkdir()
        (junk / "manifest.json").write_text(json.dumps({"id": "not-a-world"}), encoding="utf-8")
        self.assertEqual({w.id for w in catalog_worlds(self.catalog)},
                         {"tbl-world", "gph-world"})

    def test_a_gap_naming_a_declared_schema_resolves(self):
        recipe = resolve_recipe("undirected_graph", catalog=self.catalog)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.kind, CATALOG_BINDING)
        self.assertEqual(recipe.world_id, "gph-world")

    def test_a_gap_naming_a_declared_domain_resolves(self):
        self.assertEqual(resolve_recipe("numeric", catalog=self.catalog).world_id, "tbl-world")

    def test_a_gap_the_catalog_does_not_declare_stays_blocked(self):
        """The correct answer is nothing, not the nearest available dataset."""
        self.assertIsNone(resolve_recipe("protein folding kinetics", catalog=self.catalog))
        self.assertIsNone(resolve_recipe("", catalog=self.catalog))

    def test_matching_reads_the_manifest_not_a_model_opinion(self):
        recipe = match_catalog_world("graph", self.catalog)
        self.assertIn("graph", recipe.why)
        self.assertEqual(recipe.to_dict()["bytes_origin"], "already_attested_catalog_world")

    def test_already_bound_worlds_are_excluded(self):
        self.assertIsNone(
            resolve_recipe("undirected_graph", catalog=self.catalog, exclude={"gph-world"}))

    def test_derivation_takes_priority_when_the_parent_supports_it(self):
        recipe = resolve_recipe("validator_snapshots", catalog=self.catalog,
                                parent_supports_derivation=True)
        self.assertEqual(recipe.kind, DERIVED)

    def test_resolution_is_deterministic(self):
        first = resolve_recipe("graph network", catalog=self.catalog).world_id
        for _ in range(3):
            self.assertEqual(resolve_recipe("graph network", catalog=self.catalog).world_id, first)

    def test_no_recipe_reaches_the_network(self):
        """A model-chosen URL would let a model choose its own evidence."""
        source = Path(__file__).resolve().parents[1] / "src/farfield/extras/openworld/recipes.py"
        body = source.read_text(encoding="utf-8")
        for token in ("urlopen", "requests.", "http://", "https://"):
            self.assertNotIn(token, body.split('"""')[2] if body.count('"""') > 2 else body)

    def test_available_recipes_reports_only_what_can_be_satisfied(self):
        found = available_recipes(["numeric_table", "protein folding"], catalog=self.catalog)
        self.assertEqual(set(found), {"numeric_table"})


class AcquireExecutorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.catalog = _catalog(self.root)
        self.workspace = self.root / "ws"
        self.env = OpenWorld(workspace=self.workspace)
        self.env.state.goal = "does structure change connectivity?"
        # Choosing the object of study is a scope decision, so the contract has
        # to authorise it before ACQUIRE may bind a catalog world.
        self.env.state.contract = {"root_question": self.env.state.goal,
                                   "world_selection": "catalog_match"}
        from farfield.extras.openworld.worldio import bind_fixture
        from farfield.extras.world import load_fixture

        parent = bind_fixture(self.workspace, load_fixture(self.catalog / "tbl-world"),
                              "tbl-world")
        self.env.state.world_id = parent.id
        self.env.state.world_versions.append({"id": parent.id, "world_id": parent.id,
                                              "digest": parent.digest})
        self.env._ensure_baseline()

    def tearDown(self):
        self._tmp.cleanup()

    def _acquire(self, gap):
        return self.env.execute(ActionInstance(
            SPECS["ACQUIRE"], target="Q1", frontier_target_id="Q1",
            reason="blocked_on_capability_or_world",
            extra={"gap": gap, "catalog": str(self.catalog)}))

    def test_a_catalog_world_is_bound_and_attested(self):
        result = self._acquire("undirected_graph")
        self.assertEqual(result["status"], "acquired")
        self.assertEqual(self.env.state.world_id, "gph-world")
        row = next(r for r in self.env.state.world_versions if r.get("id") == "gph-world")
        self.assertEqual(row["research_role"], "world")

    def test_an_acquired_world_is_not_a_heldout_replication_world(self):
        """One freeze must not be able to replicate itself."""
        self._acquire("undirected_graph")
        for row in self.env.state.world_versions:
            self.assertNotEqual(row.get("research_role"), "heldout")

    def test_acquisition_unlocks_the_gap_as_a_capability(self):
        self._acquire("undirected_graph")
        self.assertIn("undirected_graph", self.env.state.available_capabilities)

    def test_an_unsatisfiable_gap_still_fails_closed(self):
        result = self._acquire("protein folding kinetics")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "no_acquisition_recipe")

    def test_prior_evidence_stays_keyed_to_the_world_that_produced_it(self):
        self.env.state.record_evidence({
            "evidence_id": "E1", "world_id": "tbl-world", "world_digest": "d",
            "epistemic": "WORLD", "attested": True})
        self._acquire("undirected_graph")
        self.assertEqual(self.env.state.evidence_records[0]["world_id"], "tbl-world")

    def test_the_same_world_is_not_acquired_twice(self):
        self.assertEqual(self._acquire("undirected_graph")["status"], "acquired")
        self.assertEqual(self._acquire("undirected_graph")["status"], "blocked")

    def test_an_unauthorised_contract_refuses_to_pick_the_object_of_study(self):
        """A wrongly matched world still produces real WORLD evidence — about
        a question nobody asked. The default must be to stay blocked."""
        self.env.state.contract = {"root_question": self.env.state.goal}
        result = self._acquire("undirected_graph")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "world_selection_not_authorised_by_contract")
        self.assertEqual(result["candidate_recipes"][0]["world_id"], "gph-world")
        self.assertEqual(self.env.state.world_id, "tbl-world")

    def test_the_blocked_report_names_what_would_unlock_it(self):
        self.env.state.contract = {"root_question": self.env.state.goal}
        result = self._acquire("undirected_graph")
        self.assertIn("world_selection", result["next"])

    def test_the_acquisition_replays_from_its_event_log(self):
        from farfield.extras.openworld.reducer import rebuild_state, state_digest

        self._acquire("undirected_graph")
        self.assertEqual(state_digest(self.env.state), state_digest(rebuild_state(self.env.log)))


if __name__ == "__main__":
    unittest.main()
