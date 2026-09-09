"""Real archive adapter boundary: replay data is never counterfactual execution."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from farfield.extras import swe_trace


class AtifIngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.entries = []
        for task, reward in (("a", 1.0), ("b", 0.0)):
            for name, payload in (
                ("result.json", {"task_name": task, "verifier_result": {"rewards": {"reward": reward}}}),
                ("agent/trajectory.json", {"schema_version": "ATIF-v1.5", "steps": [
                    {"source": "user", "message": "Solve the task"},
                    {"source": "agent", "message": "actual recorded action", "observation": {
                        "results": [{"content": "Actual recorded output"}]}}],
                    "final_metrics": {"total_prompt_tokens": 100}})):
                rel = f"run-1/tasks/{task}/{name}"
                path = self.root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = json.dumps(payload).encode()
                path.write_bytes(raw)
                self.entries.append({"path": rel, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        (self.root / "manifest.json").write_text(json.dumps({"files": self.entries}))

    def ingest(self):
        reader = getattr(swe_trace, "read_atif_release", None)
        self.assertTrue(callable(reader), "no manifest-bound ATIF research adapter")
        return reader(self.root, run="run-1")

    def test_observed_labels_and_missing_returncodes_are_preserved(self):
        data = self.ingest()
        self.assertEqual([t["label"] for t in data["traces"]], ["resolved", "unresolved"])
        self.assertEqual(data["traces"][0]["steps"][0]["action"], "actual recorded action")
        self.assertIsNone(data["traces"][0]["steps"][0]["returncode"])
        self.assertEqual(data["scope"], "observational_trace_analysis_only")
        self.assertEqual(len(data["source_files"]), 4)

    def test_freeze_retains_observational_scope_and_source_manifest(self):
        from farfield.extras.freeze import freeze_world
        data = self.ingest()
        source = self.root / "projection.json"
        source.write_text(json.dumps(data))
        world = freeze_world(world_id="observed-atifs", schema="labeled_traces", slice_rule="all",
                             source_file=source, catalog=self.root / "worlds")
        payload = json.loads((world.root / "world.json").read_text())
        self.assertEqual(payload.get("research_scope"), "observational_trace_analysis_only")
        self.assertEqual(payload["source_manifest_sha256"], data["manifest_sha256"])


    def test_modified_input_cannot_be_frozen_as_attested_source(self):
        (self.root / self.entries[0]["path"]).write_text("{}")
        with self.assertRaisesRegex(swe_trace.TraceFormatError, "digest"):
            self.ingest()

    def test_missing_verifier_reward_is_not_inferred_from_trace(self):
        path = self.root / self.entries[0]["path"]
        raw = b'{"task_name":"a"}'
        path.write_bytes(raw)
        self.entries[0].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        (self.root / "manifest.json").write_text(json.dumps({"files": self.entries}))
        with self.assertRaisesRegex(swe_trace.TraceFormatError, "reward"):
            self.ingest()

    def test_timeout_is_execution_error_not_scientific_negative(self):
        path = self.root / self.entries[0]["path"]
        raw = json.dumps({"task_name": "a", "verifier_result": None,
                          "exception_info": {"exception_type": "AgentTimeoutError"}}).encode()
        path.write_bytes(raw)
        self.entries[0].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        (self.root / "manifest.json").write_text(json.dumps({"files": self.entries}))
        data = self.ingest()
        self.assertEqual(data["traces"][0]["label"], "error")
        self.assertIsNone(data["traces"][0]["source_verifier_result"])
