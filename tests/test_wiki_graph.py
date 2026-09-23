"""The wiki graph and its search, over a three-topic wiki built in memory.

The real wiki is Amazon's content and is built on each machine, so these tests
cannot rely on it. They pin what /kdp-chat depends on: both edge kinds exist,
search ranks the topic that answers ahead of one that merely mentions it, and
the neighbours it reports are the ones the topic links to.
"""
import json

import pytest

from kdp.wiki import graph


def _topic(slug, title, body, crumb="Book Formatting"):
    return (f'---\nid: {slug.upper()}\ntitle: "{title}"\nslug: {slug}\n'
            f'breadcrumb: "{crumb} > {title}"\n'
            f"source: https://kdp.amazon.com/en_US/help/topic/X\n---\n\n# {title}\n\n{body}\n")


@pytest.fixture
def wiki(tmp_path, monkeypatch):
    topics = tmp_path / "topics"
    topics.mkdir()
    (topics / "create-a-paperback-cover.md").write_text(_topic(
        "create-a-paperback-cover", "Create a Paperback Cover",
        "Spine width for cream paper is page count x 0.0025. "
        "See [trim sizes](./set-trim-size.md) for page limits."))
    (topics / "set-trim-size.md").write_text(_topic(
        "set-trim-size", "Set Trim Size, Bleed, and Margins",
        "Gutter margins grow with page count. Bleed is 0.125 inches."))
    (topics / "ebook-royalties.md").write_text(_topic(
        "ebook-royalties", "eBook Royalties", "The 70% royalty option.",
        crumb="Payments & Reports"))
    (tmp_path / "index.json").write_text(json.dumps({
        "fetched_at": "2026-01-01T00:00:00Z",
        "tree": [
            {"id": None, "title": "Book Formatting", "children": [
                {"id": "A", "title": "Create a Paperback Cover",
                 "slug": "create-a-paperback-cover", "children": [
                     {"id": "B", "title": "Set Trim Size", "slug": "set-trim-size",
                      "children": []}]}]},
            {"id": None, "title": "Payments & Reports", "children": [
                {"id": "C", "title": "eBook Royalties", "slug": "ebook-royalties",
                 "children": []}]},
        ],
    }))
    monkeypatch.setattr(graph, "WIKI", tmp_path)
    monkeypatch.setattr(graph, "TOPICS", topics)
    monkeypatch.setattr(graph, "GRAPH", tmp_path / "graph.json")
    return graph.build_graph()


def test_graph_has_sections_topics_and_both_edge_kinds(wiki):
    kinds = {n["id"]: n["kind"] for n in wiki["nodes"]}
    assert kinds["section:book-formatting"] == "section"
    assert kinds["set-trim-size"] == "topic"
    edges = {(e["source"], e["target"], e["kind"]) for e in wiki["edges"]}
    assert ("section:book-formatting", "create-a-paperback-cover", "parent") in edges
    assert ("create-a-paperback-cover", "set-trim-size", "parent") in edges
    assert ("create-a-paperback-cover", "set-trim-size", "links_to") in edges
    assert all(e["source"] != e["target"] for e in wiki["edges"])


def test_every_topic_knows_its_section(wiki):
    sections = {n["id"]: n["section"] for n in wiki["nodes"] if n["kind"] == "topic"}
    assert sections["set-trim-size"] == "Book Formatting"
    assert sections["ebook-royalties"] == "Payments & Reports"


def test_the_build_is_deterministic(wiki):
    assert graph.build_graph() == wiki


def test_search_ranks_the_answering_topic_first(wiki):
    hits = graph.search("spine width cream paper", k=3)
    assert hits[0]["id"] == "create-a-paperback-cover"
    assert ("Set Trim Size, Bleed, and Margins", "wiki/topics/set-trim-size.md") \
        in hits[0]["neighbours"]


def test_search_returns_nothing_rather_than_a_guess(wiki):
    assert graph.search("audiobook narration") == []


def test_a_missing_wiki_says_how_to_build_it(tmp_path, monkeypatch):
    monkeypatch.setattr(graph, "GRAPH", tmp_path / "graph.json")
    with pytest.raises(FileNotFoundError, match="kdp wiki build"):
        graph.load_graph()
