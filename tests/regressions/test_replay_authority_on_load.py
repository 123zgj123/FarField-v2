"""On a resume, the event log is the authority over the saved snapshot.

A real workspace loaded with a state whose digest did not match a replay of its
own log — the snapshot had been written by different derivation code. Nothing
noticed, and the session would have continued from a state the log could not
account for. Since the log is the only writer by design, it is also the
tie-break.

The record of that divergence lives on the environment, not in the state:
writing it into canonical state would change the rebuilt state's own digest,
which is the equality being protected.
"""

import json
import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld import OpenWorld
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.reducer import rebuild_state, state_digest


class ReplayAuthorityTest(unittest.TestCase):
    def workspace(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = OpenWorld(workspace=root)
        env.state = env.state.__class__(goal="does X improve Y in Z?")
        from farfield.extras.openworld.reducer import apply_events

        env.state = apply_events(env.state, [
            make_event("ContractSet", {"root_question": "does X improve Y in Z?"}),
            make_event("QuestionCreated", {"id": "Q1", "text": "does X improve Y in Z?"}),
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
        ], log=env.log)
        env.persist()
        return root

    def test_a_clean_workspace_reloads_without_divergence(self):
        env = OpenWorld.load(self.workspace())
        self.assertIsNone(env.replay_divergence)
        self.assertEqual(state_digest(env.state),
                         state_digest(rebuild_state(env.log)))

    def test_a_snapshot_that_disagrees_with_its_log_is_rebuilt(self):
        root = self.workspace()
        path = root / "SCIENTIFIC_STATE.json"
        row = json.loads(path.read_text())
        row["theories"].append({"id": "GHOST", "text": "never happened",
                                "status": "supported"})
        path.write_text(json.dumps(row))

        env = OpenWorld.load(root)
        self.assertIsNotNone(env.replay_divergence)
        self.assertEqual(env.replay_divergence["resolution"],
                         "rebuilt_from_the_event_log")
        self.assertNotIn("GHOST", [t.get("id") for t in env.state.theories])

    def test_the_rebuilt_state_still_equals_its_own_replay(self):
        """The record must not be written where it changes what it describes."""
        root = self.workspace()
        path = root / "SCIENTIFIC_STATE.json"
        row = json.loads(path.read_text())
        row["theories"].append({"id": "GHOST", "text": "never happened"})
        path.write_text(json.dumps(row))

        env = OpenWorld.load(root)
        self.assertEqual(state_digest(env.state),
                         state_digest(rebuild_state(env.log)))

    def test_a_workspace_with_no_log_keeps_its_snapshot(self):
        root = self.workspace()
        (root / "SCIENTIFIC_EVENTS.json").unlink()
        env = OpenWorld.load(root)
        self.assertIsNone(env.replay_divergence)
        self.assertEqual([t.get("id") for t in env.state.theories], ["T1"])


if __name__ == "__main__":
    unittest.main()
