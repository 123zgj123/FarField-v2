"""Far-field exploration needs a citation graph, not a keyword result set.

Six live segments produced zero grounded transitions. The cause was three
things compounding: transitions were sought only *inside* one keyword search's
six results; the references those results carried were kept as strings and never
dereferenced; and the two indexes named the same paper differently, so even a
genuine citation could not match. An OpenAlex work is keyed by DOI while its own
`referenced_works` are W-ids.
"""

import unittest

from farfield.extras.citations import (
    DIRECT_CITATION,
    FORWARD_CITATION,
    PROVENANCE_KINDS,
    RETRIEVAL_KINDS,
    BIBLIOGRAPHIC_COUPLING,
    CO_CITATION,
    EDGE_KINDS,
    CitationEdge,
    EvolutionGraph,
    ExpansionBudget,
    ExtractionBudget,
    PaperStateCache,
    expand_citations,
    recover_trajectories,
    transitions_from_graph,
)
from farfield.extras.livefeed import FeedBlocked, FreshWork
from farfield.extras.workid import WorkRegistry, canonical_from_work, parse_identifier


def work(title, wid, year, refs=(), aliases=(), source="openalex"):
    return {"title": title, "work_id": wid, "published": str(year), "source": source,
            "references": list(refs), "aliases": list(aliases), "abstract": ""}


class CanonicalIdentityTest(unittest.TestCase):
    """CASE 2: one paper via DOI, OpenAlex, arXiv and S2 is one work."""

    def test_every_namespace_is_recognised(self):
        cases = {
            "2401.00001v3": ("arxiv", "2401.00001"),
            "arXiv:2401.00001": ("arxiv", "2401.00001"),
            "https://arxiv.org/abs/2401.00001": ("arxiv", "2401.00001"),
            "doi:10.1/A": ("doi", "10.1/a"),
            "https://doi.org/10.1/a": ("doi", "10.1/a"),
            "10.1/a": ("doi", "10.1/a"),
            "W123": ("openalex", "W123"),
            "https://openalex.org/W123": ("openalex", "W123"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_identifier(raw), expected)

    def test_a_title_is_never_an_identifier(self):
        self.assertIsNone(parse_identifier("Attention Is All You Need"))
        self.assertIsNone(parse_identifier(""))

    def test_the_same_paper_from_two_indexes_is_one_canonical_work(self):
        registry = WorkRegistry()
        left = registry.add(work("P", "2401.00001", 2024, source="s2"))
        right = registry.add(work("P", "doi:10.1/p", 2024, aliases=["W9", "2401.00001"]))
        self.assertEqual(left.canonical_id, right.canonical_id)
        self.assertEqual(set(right.identifiers), {"arxiv", "doi", "openalex"})

    def test_a_w_id_reference_resolves_to_a_doi_keyed_work(self):
        """The exact live failure: neither side could ever match the other."""
        registry = WorkRegistry()
        cited = registry.add(work("Cited", "doi:10.1/cited", 2016, aliases=["W111"]))
        self.assertEqual(registry.resolve("W111"), cited.canonical_id)
        self.assertEqual(registry.resolve("https://openalex.org/W111"), cited.canonical_id)

    def test_a_shared_title_alone_does_not_merge_two_works(self):
        registry = WorkRegistry()
        registry.add(work("Same Title", "doi:10.1/a", 2020))
        other = registry.add(work("Same Title", "doi:10.2/b", 2021))
        self.assertEqual(len(registry.works), 2)
        self.assertNotEqual(registry.resolve("doi:10.1/a"), other.canonical_id)

    def test_unresolved_names_the_citations_worth_fetching(self):
        registry = WorkRegistry()
        registry.add(work("Have", "doi:10.1/a", 2020, aliases=["W1"]))
        self.assertEqual(registry.unresolved(["W1", "W2", "not-an-id"]), ["openalex:W2"])


class ExpansionTest(unittest.TestCase):
    """CASE 1: six relevant papers that do not cite each other, one with refs."""

    SEEDS = [work(f"Seed {i}", f"doi:10.1/s{i}", 2021) for i in range(5)]

    def setUp(self):
        self.seeds = list(self.SEEDS)
        self.seeds[0] = work("Seed 0", "doi:10.1/s0", 2021, refs=["W111", "W222"])
        self.library = {
            "openalex:W111": work("Cited One", "doi:10.1/c1", 2016, aliases=["W111"]),
            "openalex:W222": work("Cited Two", "doi:10.1/c2", 2018,
                                  refs=["W111"], aliases=["W222"]),
        }

    def _by_id(self, keys):
        return [self.library[key] for key in keys if key in self.library]

    def test_dereferencing_produces_real_citation_edges(self):
        graph = expand_citations(self.seeds, fetch_by_id=self._by_id,
                                 budget=ExpansionBudget(depth=2, max_nodes=20))
        self.assertGreaterEqual(len(graph.provenance_edges()), 2)
        self.assertTrue(all(edge.kind == DIRECT_CITATION
                            for edge in graph.provenance_edges()))

    def test_without_dereferencing_there_is_nothing(self):
        """The old behaviour, stated as a fact rather than assumed."""
        graph = expand_citations(self.seeds, budget=ExpansionBudget(depth=1))
        self.assertEqual(graph.provenance_edges(), [])

    def test_expansion_respects_its_node_budget(self):
        graph = expand_citations(self.seeds, fetch_by_id=self._by_id,
                                 budget=ExpansionBudget(depth=2, max_nodes=6))
        self.assertLessEqual(len(graph.registry.works), 6)

    def test_forward_expansion_records_its_own_kind(self):
        graph = expand_citations(
            self.seeds[:1],
            fetch_citing=lambda keys: [work("Later", "doi:10.1/later", 2023,
                                            refs=["W000"])],
            budget=ExpansionBudget(depth=1))
        self.assertTrue(any(edge.kind == FORWARD_CITATION for edge in graph.edges))

    def test_an_off_topic_node_is_counted_and_not_followed(self):
        graph = expand_citations(
            self.seeds, fetch_by_id=self._by_id,
            budget=ExpansionBudget(depth=1),
            relevant=lambda row: "Cited One" in str(row.get("title") or ""))
        titles = {row.get("title") for row in graph.rows.values()}
        self.assertIn("Cited One", titles)
        self.assertNotIn("Cited Two", titles)
        self.assertEqual(graph.telemetry["rejected_nodes"], 1)

    def test_a_rate_limited_source_is_blocked_not_read_as_empty(self):
        """CASE 15: a 429 must not become "this paper has no citations"."""
        graph = expand_citations(
            self.seeds, fetch_by_id=lambda keys: FeedBlocked(
                attempted="openalex", reason="429 rate limited"),
            budget=ExpansionBudget(depth=1))
        self.assertTrue(graph.blocked)
        self.assertEqual(graph.telemetry["blocked_sources"], len(graph.blocked))
        self.assertEqual(graph.provenance_edges(), [])

    def test_verified_seeds_survive_a_blocked_expansion(self):
        graph = expand_citations(
            self.seeds, fetch_by_id=lambda keys: FeedBlocked(attempted="x", reason="429"),
            budget=ExpansionBudget(depth=1))
        self.assertEqual(len(graph.registry.works), len(self.seeds))

    def test_telemetry_answers_which_stage_was_the_limit(self):
        graph = expand_citations(self.seeds, fetch_by_id=self._by_id,
                                 budget=ExpansionBudget(depth=1))
        for key in ("expansion_requests", "reference_keys_requested",
                    "rows_returned_by_sources", "citation_nodes_verified",
                    "rejected_nodes", "blocked_sources"):
            self.assertIn(key, graph.telemetry)


class EdgeKindTest(unittest.TestCase):
    """CASE 3: adjacency is not lineage."""

    def test_provenance_and_retrieval_kinds_are_disjoint(self):
        self.assertFalse(PROVENANCE_KINDS & RETRIEVAL_KINDS)

    def test_a_retrieval_relation_is_not_provenance(self):
        edge = CitationEdge(source="a", target="b", kind=BIBLIOGRAPHIC_COUPLING)
        self.assertFalse(edge.is_provenance)

    def test_only_provenance_edges_can_become_transitions(self):
        graph = EvolutionGraph()
        graph.add_work(work("A", "doi:10.1/a", 2018))
        graph.add_work(work("B", "doi:10.1/b", 2020))
        graph.add_edge(CitationEdge(source="doi:10.1/a", target="doi:10.1/b",
                                    kind=BIBLIOGRAPHIC_COUPLING))
        transitions, _ = transitions_from_graph(graph)
        self.assertEqual(transitions, [])

    def test_a_cited_work_may_not_postdate_the_work_citing_it(self):
        """CASE 4: a citation edge that inverts time is refused."""
        graph = EvolutionGraph()
        graph.add_work(work("Old", "doi:10.1/old", 2022))
        graph.add_work(work("New", "doi:10.1/new", 2015))
        added = graph.add_edge(CitationEdge(
            source="doi:10.1/old", target="doi:10.1/new", kind=DIRECT_CITATION,
            source_year="2022", target_year="2015"))
        self.assertFalse(added)
        self.assertTrue(graph.blocked)


class TrajectoryRecoveryTest(unittest.TestCase):
    """An isolated A to B is one step; a lineage is A to B to C."""

    class Fake:
        def __init__(self, source, target, operator):
            self.source_cite_id, self.target_cite_id = source, target
            self.operator, self.status = operator, "extracted"

        def to_dict(self):
            return {"source": self.source_cite_id, "target": self.target_cite_id,
                    "operator": self.operator}

    def _graph(self):
        graph = EvolutionGraph()
        for name, year in (("a", 2014), ("b", 2017), ("c", 2020)):
            graph.add_work(work(name.upper(), f"doi:10.1/{name}", year))
        return graph

    def test_a_chain_is_recovered_as_one_path(self):
        graph = self._graph()
        rows = recover_trajectories(graph, [
            self.Fake("doi:10.1/a", "doi:10.1/b", "assumption_removal"),
            self.Fake("doi:10.1/b", "doi:10.1/c", "representation_change")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["length"], 2)
        self.assertEqual(rows[0]["operator_sequence"],
                         ["assumption_removal", "representation_change"])
        self.assertEqual(rows[0]["states"],
                         ["doi:10.1/a", "doi:10.1/b", "doi:10.1/c"])

    def test_a_branch_is_kept_as_two_paths(self):
        graph = self._graph()
        graph.add_work(work("D", "doi:10.1/d", 2021))
        rows = recover_trajectories(graph, [
            self.Fake("doi:10.1/a", "doi:10.1/b", "op1"),
            self.Fake("doi:10.1/b", "doi:10.1/c", "op2"),
            self.Fake("doi:10.1/b", "doi:10.1/d", "op3")])
        self.assertEqual(len(rows), 2)

    def test_an_unknown_work_yields_no_path(self):
        self.assertEqual(
            recover_trajectories(self._graph(),
                                 [self.Fake("doi:10.1/zz", "doi:10.1/yy", "op")]), [])


if __name__ == "__main__":
    unittest.main()


class ExtractionCostTest(unittest.TestCase):
    """CASE 5: a bounded survey may not outspend a whole run's call budget.

    The first version re-extracted both endpoints of every edge, so a paper
    sitting on five edges was read five times and a 24-edge graph could cost
    forty-eight model calls inside a run allowed twenty-four. Expanded nodes
    are read from title, abstract, year and references only; the fix is not to
    read less of each paper but to stop reading the same paper again.
    """

    class CountingClient:
        def __init__(self, payload=None):
            self.calls: list[str] = []
            self.payload = payload or "{}"

        def complete(self, prompt, *, purpose="", system=None, **kwargs):
            self.calls.append(purpose)
            return type("C", (), {"text": self.payload})()

    @staticmethod
    def paper(title, wid, year, mechanism, refs=()):
        abstract = f"We study {title}. Our method uses {mechanism} throughout."
        return {"title": title, "work_id": wid, "published": str(year),
                "source": "openalex", "references": list(refs), "abstract": abstract,
                "field_spans": {"mechanism": {"value": mechanism, "quote": mechanism,
                                              "section": "abstract"}}}

    def hub_graph(self):
        """One work cited by four later works: four edges over five nodes."""
        graph = EvolutionGraph()
        graph.add_work(self.paper("roots", "doi:10.1/hub", 2015, "a linear classifier"))
        for index in range(4):
            graph.add_work(self.paper(f"branch {index}", f"doi:10.1/b{index}", 2020,
                                      f"a kernel machine {index}",
                                      refs=["doi:10.1/hub"]))
            graph.add_edge(CitationEdge(source="doi:10.1/hub",
                                        target=f"doi:10.1/b{index}",
                                        kind=DIRECT_CITATION,
                                        source_year="2015", target_year="2020"))
        return graph

    def test_a_work_on_four_edges_is_extracted_once(self):
        graph = self.hub_graph()
        client = self.CountingClient()
        transitions, _ = transitions_from_graph(graph, client=client,
                                                budget=ExtractionBudget(annotated_edges=0))
        extraction = graph.telemetry["extraction"]
        self.assertEqual(extraction["papers_cached"], 5)
        self.assertEqual(client.calls.count("research_paper_state"), 5,
                         "the hub must not be re-extracted once per edge")
        self.assertEqual(extraction["paper_extractions_with_a_client"], 5)
        self.assertEqual(extraction["edge_endpoint_lookups"], 8)
        self.assertEqual(extraction["extractions_avoided"], 3,
                         "the old version paid for eight reads of five papers")
        self.assertEqual(len(transitions), 4)

    def test_the_paper_budget_caps_model_calls(self):
        graph = self.hub_graph()
        client = self.CountingClient()
        transitions_from_graph(graph, client=client,
                               budget=ExtractionBudget(papers=2, annotated_edges=0))
        self.assertEqual(client.calls.count("research_paper_state"), 2)
        self.assertEqual(graph.telemetry["extraction"]["paper_budget_exhausted"], 3)

    def test_a_spent_budget_extracts_without_a_client_rather_than_guessing(self):
        """An exhausted budget yields ungrounded states, which refuse."""
        graph = self.hub_graph()
        cache = PaperStateCache(graph.registry, limit=0)
        state = cache.get("doi:10.1/hub", graph.rows["doi:10.1/hub"],
                          client=self.CountingClient())
        self.assertIsNotNone(state)
        self.assertEqual(cache.calls, 0)
        self.assertEqual(cache.exhausted, 1)
        self.assertEqual(state.provenance["extraction"], "explicit_spans")

    def test_annotation_is_spent_on_the_largest_delta_not_the_first_edge(self):
        graph = EvolutionGraph()
        graph.add_work(self.paper("root", "doi:10.1/r", 2015, "a linear classifier"))
        small = {"title": "small", "work_id": "doi:10.1/s", "published": "2020",
                 "source": "openalex", "references": ["doi:10.1/r"],
                 "abstract": "We study small. Our method uses a linear classifier throughout.",
                 "field_spans": {"mechanism": {"value": "a linear classifier",
                                               "quote": "a linear classifier",
                                               "section": "abstract"},
                                 "objective": {"value": "small", "quote": "small",
                                               "section": "abstract"}}}
        graph.add_work(small)
        graph.add_work(self.paper("large", "doi:10.1/l", 2021, "a kernel machine",
                                  refs=["doi:10.1/r"]))
        for target in ("doi:10.1/s", "doi:10.1/l"):
            graph.add_edge(CitationEdge(source="doi:10.1/r", target=target,
                                        kind=DIRECT_CITATION, source_year="2015",
                                        target_year="2020"))
        client = self.CountingClient()
        transitions, _ = transitions_from_graph(
            graph, client=client, budget=ExtractionBudget(annotated_edges=1))
        self.assertEqual(client.calls.count("research_transition"), 1)
        self.assertEqual(graph.telemetry["extraction"]["annotation_calls"], 1)
        annotated = [t for t in transitions
                     if t.provenance["operator"] == "quoted_interpretation"
                     or t.extraction_spans.get("annotations")]
        self.assertLessEqual(len(annotated), 1)

    def test_a_shared_cache_is_not_charged_twice(self):
        """The anchor stage and the graph stage read the same seed papers."""
        graph = self.hub_graph()
        client = self.CountingClient()
        cache = PaperStateCache(graph.registry, limit=10)
        anchor = cache.get(cache.key("doi:10.1/hub"), graph.rows["doi:10.1/hub"],
                           client=client)
        self.assertIsNotNone(anchor)
        transitions_from_graph(graph, client=client, cache=cache,
                               budget=ExtractionBudget(annotated_edges=0))
        self.assertEqual(client.calls.count("research_paper_state"), 5,
                         "the anchor's extraction is reused by every edge on the hub")

    def test_telemetry_states_that_no_full_text_was_fetched(self):
        graph = self.hub_graph()
        transitions_from_graph(graph, budget=ExtractionBudget(annotated_edges=0))
        extraction = graph.telemetry["extraction"]
        self.assertFalse(extraction["full_text_fetched_for_expanded_nodes"])
        self.assertEqual(extraction["extractions_and_annotations"], 0)
        self.assertLessEqual(extraction["extractions_and_annotations"],
                             extraction["budget"]["max_model_calls"])


class ForwardExpansionTest(unittest.TestCase):
    """CASE 6: "nobody cites this" and "I asked with the wrong key" differ.

    The forward index takes OpenAlex W-ids and nothing else, while nearly
    every work here is canonically keyed by DOI. Requiring a W-id made the
    forward request return an empty list for almost every node, which reads
    exactly like a paper nobody has cited — and no forward edge ever appeared
    in a graph.
    """

    @staticmethod
    def openalex_row(wid, title, year, refs=()):
        return {"id": f"https://openalex.org/{wid}", "display_name": title,
                "publication_year": year, "doi": f"https://doi.org/10.1/{wid.lower()}",
                "referenced_works": [f"https://openalex.org/{r}" for r in refs],
                "ids": {"openalex": f"https://openalex.org/{wid}"}}

    def test_a_doi_key_is_resolved_before_the_forward_request(self):
        import json as _json

        from farfield.extras.sources import fetch_openalex_citing

        asked: list[str] = []

        def fetcher(url, **kwargs):
            asked.append(url)
            if "cites%3A" in url or "cites:" in url:
                return _json.dumps({"results": [
                    self.openalex_row("W9", "later work", 2023)]}).encode()
            return _json.dumps({"results": [
                self.openalex_row("W1", "the cited work", 2015)]}).encode()

        works = fetch_openalex_citing(["doi:10.1/w1"], fetcher=fetcher)
        self.assertEqual(len(asked), 2, "a DOI key needs one resolve then one query")
        self.assertEqual([w.title for w in works], ["later work"])

    def test_a_known_openalex_alias_skips_the_resolve_request(self):
        graph = EvolutionGraph()
        seed = work("seed", "doi:10.1/seed", 2015, aliases=["W1"])
        graph.add_work(seed)
        asked: list[str] = []

        def fetch_citing(keys):
            asked.extend(keys)
            return [FreshWork.from_dict(work("citer", "doi:10.1/citer", 2022,
                                             refs=["W1"]))]

        graph = expand_citations([seed], fetch_citing=fetch_citing,
                                 budget=ExpansionBudget(depth=1))
        self.assertEqual(asked, ["openalex:W1"],
                         "the W-id arrived with the record; asking by DOI would "
                         "have paid for a resolve")
        forward = [e for e in graph.edges if e.kind == FORWARD_CITATION]
        self.assertEqual(len(forward), 1)
        self.assertEqual(forward[0].source, "doi:10.1/seed")

    def test_an_arxiv_only_reference_is_counted_not_silently_dropped(self):
        """A key this index cannot resolve shows up as a requested-minus-fetched gap."""
        graph = EvolutionGraph()
        seed = work("seed", "doi:10.1/seed", 2015, refs=["arXiv:2401.00001"])
        graph = expand_citations([seed], fetch_by_id=lambda keys: [],
                                 budget=ExpansionBudget(depth=1))
        telemetry = graph.telemetry
        self.assertEqual(telemetry["reference_keys_requested"], 1)
        self.assertEqual(telemetry["rows_returned_by_sources"], 0)


class ConcurrentExtractionTest(unittest.TestCase):
    """CASE 7: independent reads should not be serialised, and must not race.

    A live extraction can take over a minute. Ten papers read in sequence cost
    a quarter of an hour of wall clock on work that has no ordering at all.
    Running them together is only safe if the budget cannot be raced past, so
    the allocation happens before dispatch rather than inside each worker.
    """

    class SlowClient:
        def __init__(self, delay=0.02):
            import threading

            self.delay = delay
            self.calls = 0
            self.concurrent = 0
            self.peak = 0
            self._lock = threading.Lock()

        def complete(self, prompt, *, purpose="", system=None, **kwargs):
            import time

            with self._lock:
                self.calls += 1
                self.concurrent += 1
                self.peak = max(self.peak, self.concurrent)
            time.sleep(self.delay)
            with self._lock:
                self.concurrent -= 1
            return type("C", (), {"text": "{}"})()

    def rows(self, count):
        return [(f"doi:10.1/p{index}",
                 {"title": f"paper {index}", "work_id": f"doi:10.1/p{index}",
                  "published": "2020", "abstract": "an abstract", "references": []})
                for index in range(count)]

    def test_the_budget_cannot_be_raced_past(self):
        client = self.SlowClient()
        cache = PaperStateCache(limit=3)
        cache.prefetch(self.rows(8), client=client, workers=8)
        self.assertEqual(client.calls, 3, "three slots, eight papers, three calls")
        self.assertEqual(cache.calls, 3)
        self.assertEqual(cache.exhausted, 5)
        self.assertEqual(len(cache.states), 8,
                         "the five over budget are still extracted, without a client")

    def test_independent_extractions_overlap(self):
        client = self.SlowClient()
        cache = PaperStateCache(limit=6)
        cache.prefetch(self.rows(6), client=client, workers=4)
        self.assertEqual(client.calls, 6)
        self.assertGreater(client.peak, 1, "six independent reads ran one at a time")

    def test_a_cached_work_is_never_re_extracted_by_a_prefetch(self):
        client = self.SlowClient()
        cache = PaperStateCache(limit=6)
        rows = self.rows(4)
        cache.get(*rows[0], client=client)
        cache.prefetch(rows, client=client, workers=4)
        self.assertEqual(client.calls, 4)


class RestoredLineageTest(unittest.TestCase):
    """CASE 9: verification must use the same rule at both ends.

    Extraction resolved a citation through a canonical registry. Reading the
    transition back from the survey artifact compared raw strings, so the
    namespace mismatch the registry exists to settle reappeared at read time:
    ten grounded transitions from a live citation graph restored as ten blocked
    ones, and the lane that had finally found something could not use any of it.
    """

    @staticmethod
    def paper(title, wid, year, representation, refs=(), aliases=()):
        abstract = f"We study {title}. The data is represented as {representation}."
        return {"title": title, "work_id": wid, "published": str(year),
                "source": "openalex", "references": list(refs),
                "aliases": list(aliases), "abstract": abstract,
                "field_spans": {"representation": {"value": representation,
                                                   "quote": representation,
                                                   "section": "abstract"}}}

    def cross_namespace_transition(self):
        """A DOI-keyed work cited by its OpenAlex id — the live case."""
        graph = EvolutionGraph()
        graph.add_work(self.paper("roots", "doi:10.1/a", 2015,
                                  "a dense token grid", aliases=["W1"]))
        graph.add_work(self.paper("branch", "doi:10.1/b", 2020,
                                  "a sparse retrieval index", refs=["W1"]))
        graph.add_edge(CitationEdge(source="doi:10.1/a", target="doi:10.1/b",
                                    kind=DIRECT_CITATION, source_year="2015",
                                    target_year="2020"))
        transitions, _ = transitions_from_graph(
            graph, budget=ExtractionBudget(annotated_edges=0))
        self.assertEqual(len(transitions), 1)
        return transitions[0].to_dict()

    def test_a_serialized_transition_still_verifies(self):
        from farfield.extras.explore import _research_restore_transition

        row = self.cross_namespace_transition()
        self.assertEqual(row["provenance"]["identity"]["matched_reference"], "W1")
        restored = _research_restore_transition(row)
        self.assertEqual(restored.status, "extracted")
        self.assertEqual(restored.reasons, ())

    def test_a_reference_the_target_never_reported_is_refused(self):
        from farfield.extras.explore import _research_restore_transition

        row = self.cross_namespace_transition()
        row["provenance"]["identity"]["matched_reference"] = "W999"
        restored = _research_restore_transition(row)
        self.assertEqual(restored.status, "blocked")
        self.assertIn("missing_citation_lineage", restored.reasons)

    def test_identifiers_that_do_not_name_the_source_are_refused(self):
        from farfield.extras.explore import _research_restore_transition

        row = self.cross_namespace_transition()
        row["provenance"]["identity"]["source_keys"] = ["openalex:W1"]
        restored = _research_restore_transition(row)
        self.assertEqual(restored.status, "blocked",
                         "keys that do not include the source's own cite id "
                         "could belong to any paper")

    def test_a_transition_retrieved_after_a_round_trip(self):
        """The end-to-end property the live run needed and did not have."""
        from farfield.extras.explore import retrieve_transitions

        row = self.cross_namespace_transition()
        selected = retrieve_transitions({"representation": "a dense token grid"}, [row])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].operator, "representation_change")
        self.assertEqual(selected[0].retrieval["applicability"], "established")


class RetrievalRelationTest(unittest.TestCase):
    """CASE 12: a kind nothing produces is a claim the runtime cannot keep.

    Four retrieval kinds were declared and no code built one, so the separation
    between "came after and cited it" and "the literature treats these as
    related" only had one side. The two that can be computed from reference
    lists already in the graph are now built; the two that nothing computed are
    gone.
    """

    def graph(self):
        rows = [
            work("shared source one", "doi:10.1/s1", 2010),
            work("shared source two", "doi:10.1/s2", 2011),
            work("left", "doi:10.1/l", 2020, refs=["doi:10.1/s1", "doi:10.1/s2"]),
            work("right", "doi:10.1/r", 2021, refs=["doi:10.1/s1", "doi:10.1/s2"]),
        ]
        return expand_citations(rows, budget=ExpansionBudget(seeds=4, depth=1))

    def test_two_works_citing_the_same_sources_are_coupled(self):
        graph = self.graph()
        coupled = [e for e in graph.edges if e.kind == BIBLIOGRAPHIC_COUPLING]
        self.assertEqual([(e.source, e.target) for e in coupled],
                         [("doi:10.1/l", "doi:10.1/r")])
        self.assertEqual(coupled[0].reported_by, "shared_references:2")
        self.assertEqual(graph.telemetry["bibliographic_coupling_edges"], 1)

    def test_two_works_cited_together_are_co_cited(self):
        graph = self.graph()
        cocited = [e for e in graph.edges if e.kind == CO_CITATION]
        self.assertEqual([(e.source, e.target) for e in cocited],
                         [("doi:10.1/s1", "doi:10.1/s2")])
        self.assertGreaterEqual(graph.telemetry["co_citation_edges"], 1)

    def test_a_single_shared_source_is_not_coupling(self):
        graph = expand_citations([
            work("source", "doi:10.1/s", 2010),
            work("left", "doi:10.1/l", 2020, refs=["doi:10.1/s"]),
            work("right", "doi:10.1/r", 2021, refs=["doi:10.1/s"]),
        ], budget=ExpansionBudget(seeds=3, depth=1))
        self.assertEqual([e for e in graph.edges if e.kind == BIBLIOGRAPHIC_COUPLING], [])

    def test_no_retrieval_relation_becomes_a_transition(self):
        graph = self.graph()
        self.assertTrue([e for e in graph.edges if e.kind in RETRIEVAL_KINDS])
        transitions, _ = transitions_from_graph(graph)
        for transition in transitions:
            self.assertIn(transition.provenance["lineage"], {"target.references"})
        considered = graph.telemetry.get("extraction", {}).get(
            "provenance_edges_considered", 0)
        self.assertEqual(considered, len(graph.provenance_edges()))

    def test_every_declared_kind_is_actually_built(self):
        """The check that would have caught four ghost kinds.

        Behavioural, not textual: one expansion over a fixture shaped to
        produce every kind, then a comparison against the declared vocabulary.
        A kind nothing can build fails here rather than sitting in a constant.
        """
        seeds = [
            work("shared source one", "doi:10.1/s1", 2010),
            work("shared source two", "doi:10.1/s2", 2011),
            work("left", "doi:10.1/l", 2020, refs=["doi:10.1/s1", "doi:10.1/s2"]),
            work("right", "doi:10.1/r", 2021, refs=["doi:10.1/s1", "doi:10.1/s2"]),
        ]
        graph = expand_citations(
            seeds,
            fetch_citing=lambda keys: [FreshWork.from_dict(
                work("citer", "doi:10.1/c", 2023, refs=["doi:10.1/l"]))]
            if keys == ["doi:10.1/l"] else [],
            budget=ExpansionBudget(seeds=4, depth=1))
        built = {edge.kind for edge in graph.edges}
        self.assertEqual(built, set(EDGE_KINDS),
                         f"declared but never built: {set(EDGE_KINDS) - built}")
