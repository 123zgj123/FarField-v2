"""Words are not subjects.

A live run on *does petal geometry separate iris species better than sepal
geometry?* called a paper on first-order conic programming "on topic" because
its abstract contained "petal" and "geometry" — two of seven anchor terms. The
lexical guard says in its own output that it cannot tell a subject from a
shared word. One batched call over titles and abstracts can, and it is allowed
to withhold relevance but never to invent it.
"""

import json
import unittest

from farfield.extras.openworld.exploration import relevance_report, subject_screen

ROOT = "does petal geometry separate iris species better than sepal geometry?"
OPTIMIZATION = {"cite_id": "A", "problem": "", "research_question": "",
                "title": "Afterimage Slow Regions in First-Order Methods for "
                         "Linear Conic Programming",
                "abstract": "the petal geometry of the residual field on the state space"}
MORPHOMETRICS = {"cite_id": "B", "problem": "", "research_question": "",
                 "title": "Petal and sepal morphometrics discriminate Iris species",
                 "abstract": "petal length width sepal iris species geometry discriminant"}


class Stub:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, prompt, *, purpose="", system=None, **kwargs):
        self.calls += 1
        self.last = prompt
        return type("C", (), {"text": self.payload})()


def verdicts(*rows):
    return Stub(json.dumps({"verdicts": list(rows)}))


class SubjectScreenTest(unittest.TestCase):
    def test_the_lexical_guard_alone_admits_the_wrong_paper(self):
        """The old behaviour, stated as a fact rather than assumed."""
        rows = relevance_report(ROOT, [OPTIMIZATION, MORPHOMETRICS])["papers"]
        self.assertEqual([row["relevance"] for row in rows], ["on_topic", "on_topic"])

    def test_a_paper_about_another_subject_is_demoted(self):
        client = verdicts(
            {"cite_id": "A", "about_the_subject": False, "subject": "convex optimization",
             "reason": "It concerns conic programming convergence, not flowers."},
            {"cite_id": "B", "about_the_subject": True, "subject": "iris morphometrics",
             "reason": "It measures petal and sepal geometry across Iris species."})
        report = relevance_report(ROOT, [OPTIMIZATION, MORPHOMETRICS], client=client)
        self.assertEqual(report["usable"], ["B"])
        demoted = next(row for row in report["papers"] if row["cite_id"] == "A")
        self.assertEqual(demoted["relevance"], "off_topic")
        self.assertEqual(demoted["demoted_from"], "on_topic")
        self.assertIn("conic programming", demoted["reason"])

    def test_one_call_screens_the_whole_retrieval(self):
        client = verdicts({"cite_id": "A", "about_the_subject": False})
        relevance_report(ROOT, [OPTIMIZATION, MORPHOMETRICS], client=client)
        self.assertEqual(client.calls, 1)

    def test_the_screen_can_only_withhold_relevance_never_invent_it(self):
        unrelated = {"cite_id": "A", "title": "a wholly unrelated title",
                     "abstract": "nothing in common", "problem": "",
                     "research_question": ""}
        client = verdicts({"cite_id": "A", "about_the_subject": True,
                           "subject": "iris", "reason": "trust me"})
        report = relevance_report(ROOT, [unrelated], client=client)
        self.assertEqual(report["usable"], [])
        self.assertEqual(report["papers"][0]["relevance"], "off_topic")

    def test_an_unavailable_screen_leaves_every_lexical_verdict_standing(self):
        class Broken:
            def complete(self, *args, **kwargs):
                raise ValueError("no route to host")

        report = relevance_report(ROOT, [OPTIMIZATION], client=Broken())
        self.assertTrue(report["subject_screen"]["status"].startswith("screen_unavailable"))
        self.assertEqual(report["papers"][0]["relevance"], "on_topic")

    def test_a_malformed_answer_filters_nothing(self):
        report = relevance_report(ROOT, [OPTIMIZATION], client=Stub("not json at all"))
        self.assertEqual(report["subject_screen"]["status"], "screen_malformed")
        self.assertEqual(report["papers"][0]["relevance"], "on_topic")

    def test_a_verdict_about_a_paper_that_was_not_sent_is_ignored(self):
        client = verdicts({"cite_id": "ghost", "about_the_subject": False},
                          {"cite_id": "A", "about_the_subject": False})
        screen = subject_screen(ROOT, [OPTIMIZATION], client)
        self.assertEqual(screen["off_subject"], ["A"])
        self.assertNotIn("ghost", screen["subjects"])

    def test_a_paper_the_screen_did_not_judge_is_reported_not_dropped(self):
        client = verdicts({"cite_id": "A", "about_the_subject": False})
        screen = subject_screen(ROOT, [OPTIMIZATION, MORPHOMETRICS], client)
        self.assertEqual(screen["unjudged"], ["B"])

    def test_no_client_means_no_call_and_no_screening(self):
        screen = subject_screen(ROOT, [OPTIMIZATION], None)
        self.assertEqual(screen["status"], "not_screened")
        self.assertEqual(screen["off_subject"], [])

    def test_the_screen_is_sent_titles_and_abstracts_not_full_texts(self):
        client = verdicts({"cite_id": "A", "about_the_subject": True})
        subject_screen(ROOT, [{**OPTIMIZATION, "full_text": "x" * 5000}], client)
        sent = json.loads(client.last)
        self.assertEqual(sorted(sent["papers"][0]), ["abstract", "cite_id", "title"])


class SearchTopicTest(unittest.TestCase):
    """CASE 10: ask an index for the subject, not for the question's wording.

    The phrase builder takes adjacent word pairs in sentence order, so "does
    petal geometry separate iris species better than sepal geometry?" became
    the query `all:"does petal"` — and a live survey returned conic
    programming, nanophotonics and cut-flower senescence. "iris species", the
    one phrase naming the subject, was never queried at all.
    """

    def test_a_question_is_turned_into_a_search_phrase(self):
        from farfield.extras.openworld.exploration import search_topic

        client = Stub(json.dumps({"topic": "iris species petal sepal morphometrics",
                                  "subject": "iris flowers"}))
        result = search_topic(ROOT, "", client=client)
        self.assertEqual(result["topic"], "iris species petal sepal morphometrics")
        self.assertEqual(result["basis"], "model_named_subject_and_phenomenon")

    def test_the_phrase_actually_changes_the_query(self):
        from farfield.extras.livefeed import survey_queries

        before = survey_queries(ROOT, ROOT, topic=ROOT)
        after = survey_queries("iris species petal sepal morphometrics",
                               "iris species petal sepal morphometrics",
                               topic="iris species petal sepal morphometrics")
        self.assertNotIn("iris species", " ".join(before))
        self.assertIn("iris species", " ".join(after))

    def test_a_question_word_never_starts_a_search_phrase(self):
        from farfield.extras.livefeed import object_survey_phrases

        for question in (ROOT,
                         "how does retrieval augmentation change factual accuracy?",
                         "can sparse attention preserve accuracy at long lengths?",
                         "is a deeper model better than a wider one for tabular data?"):
            with self.subTest(question=question):
                first = object_survey_phrases(question)[0].split()[0].casefold()
                self.assertNotIn(first, {"does", "how", "can", "is", "what", "why",
                                         "whether", "better", "than"})

    def test_no_client_leaves_the_question_as_it_was(self):
        from farfield.extras.openworld.exploration import search_topic

        result = search_topic(ROOT, "", client=None)
        self.assertEqual(result["topic"], ROOT)
        self.assertEqual(result["basis"], "root_question_verbatim")

    def test_an_unusable_answer_falls_back_rather_than_searching_for_nothing(self):
        from farfield.extras.openworld.exploration import search_topic

        for payload, basis in ((json.dumps({"topic": "iris"}), "unusable_length"),
                               (json.dumps({"topic": " ".join(["w"] * 20)}),
                                "unusable_length"),
                               ("not json", "malformed")):
            with self.subTest(basis=basis):
                result = search_topic(ROOT, "", client=Stub(payload))
                self.assertEqual(result["topic"], ROOT)
                self.assertEqual(result["basis"], basis)

    def test_one_call_names_the_subject(self):
        from farfield.extras.openworld.exploration import search_topic

        client = Stub(json.dumps({"topic": "iris species petal sepal morphometrics"}))
        search_topic(ROOT, "which geometry separates the species?", client=client)
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
