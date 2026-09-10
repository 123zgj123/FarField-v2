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
    SEMANTIC_NEIGHBOR,
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
        for key in ("citation_nodes_requested", "citation_nodes_fetched",
                    "citation_nodes_verified", "rejected_nodes", "blocked_sources"):
            self.assertIn(key, graph.telemetry)


class EdgeKindTest(unittest.TestCase):
    """CASE 3: adjacency is not lineage."""

    def test_provenance_and_retrieval_kinds_are_disjoint(self):
        self.assertFalse(PROVENANCE_KINDS & RETRIEVAL_KINDS)

    def test_a_semantic_neighbour_is_not_provenance(self):
        edge = CitationEdge(source="a", target="b", kind=SEMANTIC_NEIGHBOR)
        self.assertFalse(edge.is_provenance)

    def test_only_provenance_edges_can_become_transitions(self):
        graph = EvolutionGraph()
        graph.add_work(work("A", "doi:10.1/a", 2018))
        graph.add_work(work("B", "doi:10.1/b", 2020))
        graph.add_edge(CitationEdge(source="doi:10.1/a", target="doi:10.1/b",
                                    kind=SEMANTIC_NEIGHBOR))
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
        self.assertEqual(extraction["model_calls_total"], 0)
        self.assertLessEqual(extraction["model_calls_total"],
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
        self.assertEqual(telemetry["citation_nodes_requested"], 1)
        self.assertEqual(telemetry["citation_nodes_fetched"], 0)
