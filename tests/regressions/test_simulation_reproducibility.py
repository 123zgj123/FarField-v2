"""A simulation must give the same answer in a different process.

`forward_simulate` documents itself as deterministic given world digest, lever,
seed and horizon, and `report_digest` is recorded as the provenance of a
result. It was not deterministic. The graph `rewire` lever built its pool with
`list({...})` and then indexed into it with a seeded `choice`, so the generator
was reproducible and the pool's order was not: repeated runs of an identical
script returned different graphs and different report digests.

Nothing caught it. Every audit in this repository checks whether a declaration
matches an implementation; none of them checks whether running the same thing
twice gives the same answer. This does, in-process for every world, and across
processes for the lever that broke.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from farfield.extras import dynworld
from farfield.extras.openworld.worldio import bind_fixture

ROOT = Path(__file__).resolve().parents[2]
WORLDS = ROOT / "worlds"

CHILD = """
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, {src!r})
from farfield.extras.openworld.worldio import bind_fixture
from farfield.extras import dynworld
with tempfile.TemporaryDirectory() as d:
    f = bind_fixture(Path(d), {world!r}, "")
    out = {{}}
    for lever in dynworld.levers_of(f):
        r = dynworld.forward_simulate(f, lever, intensity=1.0, horizon=2)
        out[lever] = [r["report_digest"],
                      [dict(s.get("observables") or {{}}) for s in r["steps"]]]
    print(json.dumps(out, sort_keys=True))
"""


def worlds():
    return sorted(p.name for p in WORLDS.iterdir() if p.is_dir()) if WORLDS.is_dir() else []


def simulate(world):
    with tempfile.TemporaryDirectory() as workspace:
        fixture = bind_fixture(Path(workspace), world, "")
        out = {}
        for lever in dynworld.levers_of(fixture):
            run = dynworld.forward_simulate(fixture, lever, intensity=1.0, horizon=2)
            out[lever] = [run["report_digest"],
                          [dict(step.get("observables") or {}) for step in run["steps"]]]
        return out


class InProcessReproducibilityTest(unittest.TestCase):
    def test_every_world_and_lever_repeats_within_a_process(self):
        for world in worlds():
            with self.subTest(world=world):
                try:
                    first = simulate(world)
                except Exception:
                    continue  # a world without dynamics is not this test's business
                self.assertEqual(first, simulate(world))


class CrossProcessReproducibilityTest(unittest.TestCase):
    """The property the in-process check cannot see."""

    def child(self, world):
        result = subprocess.run(
            [sys.executable, "-c", CHILD.format(src=str(ROOT / "src"), world=world)],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        return json.loads(result.stdout)

    def test_a_graph_rewire_gives_the_same_answer_in_another_process(self):
        """The exact break: a pool built from a set, indexed by a seeded choice."""
        first, second = self.child("zachary-karate"), self.child("zachary-karate")
        self.assertEqual(first, second)
        self.assertIn("rewire", first)

    def test_the_recorded_provenance_digest_is_stable_across_processes(self):
        first, second = self.child("les-miserables"), self.child("les-miserables")
        for lever in first:
            with self.subTest(lever=lever):
                self.assertEqual(first[lever][0], second[lever][0],
                                 "report_digest is evidence provenance")


class PoolOrderingTest(unittest.TestCase):
    def test_no_lever_indexes_into_an_unordered_collection(self):
        """`list({...})` before a seeded `choice` is the shape that broke."""
        source = (ROOT / "src/farfield/extras/dynworld.py").read_text()
        self.assertNotIn("list({", source,
                         "build the pool with sorted(); set order is not stable "
                         "between processes")


if __name__ == "__main__":
    unittest.main()


class OneDefinitionTest(unittest.TestCase):
    """What a world advertises and what it computes are one thing, not two.

    They used to be two. A gate filtered `observables_of` while
    `forward_simulate` called the observer directly, so a simulation reported
    measures the advertisement denied existed — the patch that fixed one
    inconsistency created another. The registry makes the advertised set the
    computed set's keys, so there is no second place to fall out of step.
    """

    def test_advertised_is_exactly_what_is_computed(self):
        for world in worlds():
            with self.subTest(world=world):
                with tempfile.TemporaryDirectory() as workspace:
                    fixture = bind_fixture(Path(workspace), world, "")
                    bridge = dynworld._bridge_of(fixture)
                    if not bridge:
                        continue
                    computed = set(bridge["observe"](bridge["load"](fixture.root)))
                    self.assertEqual(set(dynworld.observables_of(fixture)), computed)

    def test_a_lever_cannot_be_named_without_a_body(self):
        """The if/elif chain let a name exist with no implementation behind it."""
        for lever in dynworld.PROGRAM_LEVERS:
            with self.subTest(lever=lever.name):
                self.assertTrue(callable(lever.apply))
        for measure in dynworld.PROGRAM_MEASURES:
            with self.subTest(measure=measure.name):
                self.assertTrue(callable(measure.compute))

    def test_an_unregistered_lever_is_refused(self):
        with tempfile.TemporaryDirectory() as workspace:
            fixture = bind_fixture(Path(workspace), "live-swe-agent-selfmod-v1", "")
            with self.assertRaises(dynworld.DynamicsUnavailable):
                dynworld.forward_simulate(fixture, "invent_a_lever", horizon=1)

    def test_recording_an_outcome_is_not_the_same_as_an_independent_one(self):
        """`oracle` means gate-independent; a world can record returns without it."""
        with tempfile.TemporaryDirectory() as workspace:
            fixture = bind_fixture(Path(workspace), "openevolve-fnmin-s11", "")
            advertised = dynworld.observables_of(fixture)
            self.assertIn("mean_accepted_return", advertised)
            self.assertNotIn("false_accept_fraction", advertised,
                             "no independent oracle and no divergence to fall back on")
