"""A hypothesis that names a contrast the world registers must be executable.

A live run on an attested world produced two well-formed hypotheses. Each named
a registered observational contrast and a registered observable, each predicted
a direction that differed from its competing explanation, and neither could be
executed. The generic OBSERVE returns dataset descriptives; PROBE refuses a
question card because a stratum comparison is not an intervention. It is not an
intervention — and it is still evidence, which is why the kernel carries a
`QuestionEvidence` role.

What this path must never do is let a stratum comparison read as a controlled
experiment. It stays `causal_scope: none`, it cannot corroborate, and it
reports the strata it did *not* match on.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld import OpenWorld
from farfield.extras.openworld.actions import SPECS, ActionInstance
from farfield.extras.openworld.executors import execute_observe
from farfield.extras.openworld.runtime import bootstrap_research

WORLD = "live-swe-agent-selfmod-v1"
ROOT = ("when a coding agent writes its own validator during a run, does its "
        "independently measured task outcome improve?")


def env_with_world(root):
    return bootstrap_research(ROOT, Path(root), world=WORLD, world_id=WORLD)


def observe(env, **extra):
    action = ActionInstance(
        SPECS["OBSERVE"], target="Q1", frontier_target_id="Q1",
        extra={"question": {"id": "Q1", "text": ROOT}, **extra})
    return execute_observe(env, action)


class NamedContrastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = env_with_world(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_contrast_is_measured_against_a_matched_control(self):
        result = observe(self.env, contrast="contrast:validator_write",
                         observable="false_accept_fraction")
        self.assertEqual(result.status, "observed")
        evidence = result.evidence
        self.assertEqual(evidence["measurement"], "matched-contrast-v1")
        self.assertEqual(evidence["n_treatment"], 112.0)
        self.assertNotEqual(evidence["treatment"], evidence["control"])

    def test_matching_is_preferred_over_the_whole_history_comparison(self):
        """The whole-history comparison confounds the stratum with its episodes."""
        evidence = observe(self.env, contrast="contrast:validator_write",
                           observable="false_accept_fraction").evidence
        self.assertIn("matched on episode template", evidence["matching"])
        self.assertEqual(evidence["result"]["coverage"], 1.0,
                         "every treated update should find a matched control")

    def test_it_is_attested_world_evidence_and_still_not_causal(self):
        evidence = observe(self.env, contrast="contrast:validator_write",
                           observable="false_accept_fraction").evidence
        self.assertEqual(evidence["epistemic"], "WORLD")
        self.assertTrue(evidence["attested"])
        self.assertEqual(evidence["causal_scope"], "none")
        self.assertTrue(evidence["cannot_corroborate"])
        self.assertIn("does not make it an experiment", evidence["interpretation"])

    def test_it_reports_the_cells_it_could_not_match(self):
        """Silence about a dropped arm is what would make this overclaim."""
        evidence = observe(self.env, contrast="contrast:validator_write",
                           observable="false_accept_fraction").evidence
        self.assertIn("dropped for a one-sided arm", evidence["matching"])
        self.assertGreater(evidence["result"]["cells_dropped"], 0)

    def test_an_unregistered_contrast_is_refused_not_invented(self):
        result = observe(self.env, contrast="contrast:phase_of_the_moon",
                         observable="false_accept_fraction")
        self.assertEqual(result.status, "blocked")
        self.assertIn("not_registered",
                      result.events[0].payload["reason"])

    def test_an_unregistered_observable_is_refused(self):
        result = observe(self.env, contrast="contrast:validator_write",
                         observable="developer_satisfaction")
        self.assertEqual(result.status, "blocked")

    def test_without_a_contrast_this_question_has_no_observable_at_all(self):
        """Why the contrast path is not redundant with the generic one.

        The plan derived from this question asks for `validator_snapshots.json`,
        which this freeze does not carry, so the generic OBSERVE blocks and
        points at ACQUIRE. The contrast path answers from what the world *does*
        have — the same recorded history, split on a stratum it registers.
        """
        result = observe(self.env)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.events[0].payload["reason"], "NO_DATA")
        self.assertEqual(result.events[0].payload["gap"], "validator_snapshots")

    def test_the_same_contrast_yields_the_same_evidence_id(self):
        """Determinism, so a replay does not mint a second observation."""
        first = observe(self.env, contrast="contrast:divergent",
                        observable="mean_accepted_return").evidence
        second = observe(self.env, contrast="contrast:divergent",
                         observable="mean_accepted_return").evidence
        self.assertEqual(first["evidence_id"], second["evidence_id"])
        self.assertEqual(first["treatment"], second["treatment"])


class ContrastOfferingTest(unittest.TestCase):
    """The action has to be offered, or the executor is unreachable."""

    def test_a_hypothesis_naming_a_contrast_makes_one_eligible(self):
        from farfield.extras.openworld.actions import _contrast_observations

        class State:
            theories = [{
                "id": "T1", "question_id": "Q1",
                "card": {"lever": "contrast:validator_write"},
                "experiment_proposal": {"expected_outcomes": {
                    "self": {"observable": "false_accept_fraction",
                             "direction": "increase"},
                    "rival": {"observable": "false_accept_fraction",
                              "direction": "decrease"}}},
            }]

        rows = _contrast_observations(State(), {"id": "Q1"})
        self.assertEqual(rows, [{"contrast": "contrast:validator_write",
                                 "observable": "false_accept_fraction",
                                 "theory_id": "T1"}])

    def test_a_competing_explanation_does_not_propose_its_own_observation(self):
        from farfield.extras.openworld.actions import _contrast_observations

        class State:
            theories = [{"id": "T1:alt", "question_id": "Q1",
                         "role": "competing_explanation",
                         "card": {"lever": "contrast:validator_write"},
                         "experiment_proposal": {"expected_outcomes": {
                             "self": {"observable": "false_accept_fraction"}}}}]

        self.assertEqual(_contrast_observations(State(), {"id": "Q1"}), [])


if __name__ == "__main__":
    unittest.main()


class AdvertisedObservableTest(unittest.TestCase):
    """A world must not advertise a measure its payload cannot produce.

    The lever table already refuses to offer a handle the payload cannot feel.
    An observable nobody can move is the same promise broken from the other
    side, and it cost a live run half its hypotheses: one of the two predicted
    a rise in `cycle_fraction` on a freeze where no row carries `on_cycle`, so
    the measure read zero in every stratum and the prediction could never have
    been answered either way.
    """

    def fixture(self):
        return __import__(
            "farfield.extras.openworld.worldio", fromlist=["x"]
        ).bind_fixture(Path(self.enterContext(tempfile.TemporaryDirectory())),
                       WORLD, "")

    def test_a_measure_with_no_feature_behind_it_is_not_advertised(self):
        from farfield.extras.dynworld import observables_of

        self.assertNotIn("cycle_fraction", observables_of(self.fixture()))

    def test_the_measures_that_remain_are_the_ones_the_payload_carries(self):
        from farfield.extras.dynworld import observables_of

        self.assertEqual(
            observables_of(self.fixture()),
            ("accepted_fraction", "false_accept_fraction",
             "mean_accepted_return", "n_updates"))

    def test_every_advertised_measure_actually_differs_across_some_stratum(self):
        """The check that would have caught it: a measure that never moves."""
        from farfield.extras import dynworld

        fixture = self.fixture()
        advertised = set(dynworld.observables_of(fixture)) - {"n_updates"}
        moved: set[str] = set()
        whole = dict(dict(list(dynworld.forward_simulate(
            fixture, "dropout", intensity=0.0, horizon=1)["steps"])[0]
            .get("observables") or {}))
        for lever in dynworld.levers_of(fixture):
            if not dynworld.is_contrast(lever):
                continue
            stratum = dict(dict(list(dynworld.forward_simulate(
                fixture, lever, intensity=1.0, horizon=2)["steps"])[-1]
                .get("observables") or {}))
            moved |= {name for name in advertised
                      if abs(stratum.get(name, 0) - whole.get(name, 0)) > 1e-9}
        self.assertEqual(advertised - moved, set(),
                         "advertised and identical in every stratum")


class AdvertisedLeverTest(unittest.TestCase):
    """A lever nobody can feel is worse than no lever: it invites the experiment.

    `freeze_validators` was advertised on this freeze, applied at every
    intensity, and moved nothing. It writes `validator_writes` and `on_cycle`;
    only `on_cycle` is read by any observable, and this payload carries none.
    The lever was gated on the field it *writes* rather than on the field its
    effect is *read through*, so the one manipulable handle this world appeared
    to offer was inert — and an interventional experiment was planned on it.
    """

    def fixture(self):
        return __import__(
            "farfield.extras.openworld.worldio", fromlist=["x"]
        ).bind_fixture(Path(self.enterContext(tempfile.TemporaryDirectory())),
                       WORLD, "")

    def test_an_intervention_that_cannot_be_felt_is_not_advertised(self):
        from farfield.extras.dynworld import levers_of

        self.assertNotIn("freeze_validators", levers_of(self.fixture()))

    def test_this_freeze_offers_observation_and_no_intervention(self):
        """Worth stating: the question here is answerable only observationally."""
        from farfield.extras.dynworld import is_contrast, levers_of

        levers = levers_of(self.fixture())
        manipulable = [name for name in levers
                       if not is_contrast(name) and name != "dropout"]
        self.assertEqual(manipulable, [])

    def test_every_advertised_lever_moves_an_advertised_observable(self):
        """The general property, checked rather than assumed."""
        from farfield.extras import dynworld

        fixture = self.fixture()
        observables = set(dynworld.observables_of(fixture))
        whole = dict(dict(list(dynworld.forward_simulate(
            fixture, "dropout", intensity=0.0, horizon=1)["steps"])[0]
            .get("observables") or {}))
        for lever in dynworld.levers_of(fixture):
            with self.subTest(lever=lever):
                run = dynworld.forward_simulate(fixture, lever, intensity=1.0,
                                                horizon=2)
                after = dict(dict(list(run["steps"])[-1].get("observables") or {}))
                moved = [name for name in observables
                         if abs(after.get(name, 0) - whole.get(name, 0)) > 1e-9]
                self.assertTrue(moved, f"{lever} moves nothing it can be judged by")


class MatchedContrastTest(unittest.TestCase):
    """Matching on the strata the world names, or saying it could not.

    `CONTRAST_MATCHING` named episode template and updates-per-episode and
    nothing matched on them, so a difference could be the stratum or could be
    which episodes it came from. That is not hypothetical here: on this freeze
    updates from heavy episodes shift false acceptance *more* than
    validator-writing updates do, which is exactly the competing explanation
    the live run registered against its own hypothesis.
    """

    def fixture(self):
        return __import__(
            "farfield.extras.openworld.worldio", fromlist=["x"]
        ).bind_fixture(Path(self.enterContext(tempfile.TemporaryDirectory())),
                       WORLD, "")

    def test_the_effect_is_reported_with_both_arms_and_their_sizes(self):
        from farfield.extras.dynworld import matched_contrast

        row = matched_contrast(self.fixture(), "contrast:validator_write",
                               "false_accept_fraction")
        self.assertEqual(row["status"], "matched")
        self.assertEqual(row["n_treatment"], 112)
        self.assertGreater(row["n_control"], row["n_treatment"])
        self.assertEqual(row["coverage"], 1.0)

    def test_a_contrast_defined_by_a_matching_variable_is_refused(self):
        """heavy_episode *is* updates-per-episode, so no cell holds both arms."""
        from farfield.extras.dynworld import matched_contrast

        row = matched_contrast(self.fixture(), "contrast:heavy_episode",
                               "false_accept_fraction")
        self.assertEqual(row["status"], "no_matched_cell",
                         "a degenerate comparison must refuse, not return a number")

    def test_it_stays_observational_however_well_matched(self):
        from farfield.extras.dynworld import matched_contrast

        row = matched_contrast(self.fixture(), "contrast:validator_write",
                               "mean_accepted_return")
        self.assertEqual(row["causal_scope"], "none")
        self.assertIn("does not make it an experiment", row["interpretation"])

    def test_a_non_contrast_lever_is_not_treated_as_one(self):
        from farfield.extras.dynworld import matched_contrast

        row = matched_contrast(self.fixture(), "dropout", "accepted_fraction")
        self.assertEqual(row["status"], "not_a_contrast")

    def test_the_same_query_gives_the_same_numbers(self):
        from farfield.extras.dynworld import matched_contrast

        first = matched_contrast(self.fixture(), "contrast:divergent",
                                 "accepted_fraction")
        second = matched_contrast(self.fixture(), "contrast:divergent",
                                  "accepted_fraction")
        self.assertEqual(first["treatment"], second["treatment"])
        self.assertEqual(first["control"], second["control"])
