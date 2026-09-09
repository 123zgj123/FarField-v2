"""Source-bound full text, not model-invented bibliography or experiment evidence."""
import hashlib
import unittest

from farfield.extras import sources
from farfield.extras.livefeed import FeedBlocked, FreshWork

ABS = b'''<html><meta name="citation_arxiv_id" content="2601.12345">
<meta name="citation_title" content="Caching skewed table queries">
<meta name="citation_date" content="2026/01/12">
<meta name="citation_abstract" content="A fixed cache misses changing keys."></html>'''
HTML = b'''<html><article><h1>Caching skewed table queries</h1>
<p>Adaptive eviction follows changing keys.</p>
<a href="https://arxiv.org/abs/9999.99999">Unrelated navigation</a>
<ul><li class="ltx_bibitem"><a href="https://arxiv.org/abs/2408.08435v2">Prior</a></li>
<li class="ltx_bibitem">arXiv:2505.22954</li></ul></article></html>'''


class SourceDocumentTests(unittest.TestCase):
    def read(self, pages=None):
        reader = getattr(sources, "read_arxiv_document", None)
        self.assertTrue(callable(reader), "missing source-bound full-text reader")
        data = pages or {"abs": ABS, "html": HTML}
        return reader(FreshWork("Caching skewed table queries", "2026", arxiv_id="2601.12345"),
                      fetcher=lambda url: data[url.split('/')[-2]])

    def test_bibliography_only_with_raw_digest_and_exact_text(self):
        doc = self.read()
        self.assertEqual(doc["references"], ["2408.08435", "2505.22954"])
        self.assertEqual(doc["published"], "2026-01-12")
        self.assertIn("Adaptive eviction follows changing keys.", doc["full_text_spans"][0]["text"])
        self.assertEqual(doc["source_documents"][1]["sha256"], hashlib.sha256(HTML).hexdigest())
        self.assertEqual(doc["epistemic"], "SOURCE_DOCUMENT_NOT_EXPERIMENT")

    def test_wrong_primary_identity_fails_closed(self):
        doc = self.read({"abs": ABS.replace(b"2601.12345", b"2601.88888"), "html": HTML})
        self.assertIsInstance(doc, FeedBlocked)
        self.assertIn("identity", doc.reason)

    def test_error_page_cannot_supply_full_text_or_lineage(self):
        doc = self.read({"abs": ABS, "html": b"<html>Service unavailable</html>"})
        self.assertIsInstance(doc, FeedBlocked)

    def test_wrong_full_text_title_fails_closed(self):
        doc = self.read({"abs": ABS, "html": HTML.replace(b"Caching skewed table queries", b"Unrelated proteins")})
        self.assertIsInstance(doc, FeedBlocked)

    def test_revision_date_is_used_for_temporal_lineage(self):
        revised = ABS.replace(b"</html>", b'<meta name="citation_online_date" content="2026/08/15"></html>')
        self.assertEqual(self.read({"abs": revised, "html": HTML})["published"], "2026-08-15")

    def test_references_and_read_spans_reach_scientific_artifact(self):
        import tempfile
        from pathlib import Path
        from farfield.extras.openworld.workers import LegacyResearchWorkers
        from farfield.extras.openworld.state import ScientificState
        from farfield.extras.openworld.actions import ActionInstance, SPECS
        from farfield.extras.openworld.reducer import apply_events
        doc = self.read()
        class Feed:
            verify_literature = True
            def survey_around(self, *args, **kwargs):
                return [FreshWork.from_dict(doc)]
            def verify_fetcher(self, url):
                return b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Caching skewed table queries</title></entry></feed>'
            def read_work(self, work):
                return doc
        state = ScientificState(goal="Caching skewed table queries")
        state.add_question(question_id="q", text=state.goal)
        with tempfile.TemporaryDirectory() as tmp:
            result = LegacyResearchWorkers(feed=Feed(), workspace=Path(tmp)).survey(
                ActionInstance(SPECS["SURVEY"], target="q", extra={"extract_trajectories": True}), state.view())
            updated = apply_events(state, result.events)
            artifact = updated.artifacts[-1]
            self.assertEqual(tuple(artifact["paper_states"][0]["references"]), ("2408.08435", "2505.22954"))
            self.assertIn("Adaptive eviction", artifact["paper_states"][0]["text_sources"]["full_text:0"])
            self.assertFalse(updated.evidence_records)

    def test_composite_keeps_verified_seed_lineage_alongside_search_results(self):
        from farfield.extras.livefeed import CompositeFeed
        import inspect
        self.assertIn("seed_ids", inspect.signature(CompositeFeed).parameters,
                      "a mission cannot supply literature retrieval seeds")
        class Search:
            def survey_around(self, *args, **kwargs):
                return [FreshWork("Other caching result", "2026-02-01", arxiv_id="2602.22222")]
        feed = CompositeFeed(arxiv=Search(), scholar=lambda *a, **k: [],
            openalex=lambda *a, **k: [], seed_ids=("2601.12345",),
            document_fetcher=lambda url: ABS if "/abs/" in url else HTML)
        works = feed.survey_around("cache", "eviction", topic="cache eviction")
        self.assertEqual([w.cite_id() for w in works], ["2601.12345", "2602.22222"])
        self.assertTrue(feed.verify_literature)
        self.assertEqual(feed.read_work(works[0])["references"], ["2408.08435", "2505.22954"])
