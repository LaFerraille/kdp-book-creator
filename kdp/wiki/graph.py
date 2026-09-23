"""The wiki as a graph, and keyword search over it.

Nodes are the eleven help-centre sections and the topics under them. Edges are
of two kinds, and both matter for retrieval:

- ``parent``    the sidebar arborescence: a section or topic to its children
- ``links_to``  in-body cross references, which is how KDP says "the rule you
                are reading depends on this other one"

Search is BM25 over each topic's title, breadcrumb and body, then one hop out
along the edges: the answer to "how wide is my spine" is in the cover topic,
but the page-count limits it depends on are one link away.
"""
import json
import math
import re
from collections import Counter, defaultdict

from . import GRAPH, TOPICS, WIKI

LINK_RE = re.compile(r"\]\(\./([a-z0-9-]+)\.md\)")
WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
STOPWORDS = set("""a an and are as at be by can do does for from how i if in is it
its my of on or should that the this to what when where which who why will with
you your""".split())


def _front_matter(text):
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, _, value = line.partition(": ")
        meta[key] = json.loads(value) if value.startswith('"') else value
    return meta, body


def _fold(word):
    """Fold plurals, so "copy" finds "copies" and "margin" finds "margins"."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text):
    return [_fold(w) for w in WORD_RE.findall(text.lower()) if w not in STOPWORDS]


def build_graph():
    """Write wiki/graph.json from topics/ and index.json. Returns the graph."""
    index = json.loads((WIKI / "index.json").read_text(encoding="utf-8"))
    nodes, edges = {}, set()

    for path in sorted(TOPICS.glob("*.md")):
        meta, body = _front_matter(path.read_text(encoding="utf-8"))
        slug = meta["slug"]
        nodes[slug] = {
            "id": slug, "kind": "topic", "title": meta["title"],
            "kdp_id": meta["id"], "breadcrumb": meta["breadcrumb"],
            "section": None, "source": meta["source"],
            "path": f"wiki/topics/{slug}.md",
        }
        for target in LINK_RE.findall(body):
            if target != slug:
                edges.add((slug, target, "links_to"))

    def walk(children, parent, section):
        for n in children:
            if n.get("slug"):
                nodes[n["slug"]]["section"] = section
                edges.add((parent, n["slug"], "parent"))
                walk(n["children"], n["slug"], section)
            else:
                walk(n["children"], parent, section)

    for top in index["tree"]:
        sid = "section:" + re.sub(r"[^a-z0-9]+", "-", top["title"].lower()).strip("-")
        nodes[sid] = {"id": sid, "kind": "section", "title": top["title"]}
        if top.get("slug"):  # a section heading that is also a topic
            edges.add((sid, top["slug"], "parent"))
        walk(top["children"], sid, top["title"])

    # Topics reachable only by cross-reference keep the section of their breadcrumb.
    for n in nodes.values():
        if n["kind"] == "topic" and n["section"] is None:
            crumbs = n["breadcrumb"].split(" > ")
            n["section"] = crumbs[0] if crumbs[0] else "Other"

    graph = {
        "fetched_at": index["fetched_at"],
        "nodes": [nodes[k] for k in sorted(nodes)],
        "edges": [{"source": s, "target": t, "kind": k}
                  for s, t, k in sorted(edges) if s != t and s in nodes and t in nodes],
    }
    GRAPH.write_text(json.dumps(graph, indent=1) + "\n", encoding="utf-8")
    return graph


def load_graph():
    if not GRAPH.exists():
        raise FileNotFoundError(
            "The KDP wiki has not been built yet. Run `kdp wiki build`.")
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def search(query, k=5, graph=None):
    """Rank topics for a question. Each hit carries its linked neighbours."""
    graph = graph or load_graph()
    topics = [n for n in graph["nodes"] if n["kind"] == "topic"]
    docs = {}
    for n in topics:
        body = (TOPICS / f"{n['id']}.md").read_text(encoding="utf-8")
        # The title says what a topic is about; weight it over passing mentions.
        docs[n["id"]] = Counter(tokens(f"{n['title']} " * 3 + n["breadcrumb"] + " " + body))

    terms = set(tokens(query))
    avg = sum(sum(c.values()) for c in docs.values()) / len(docs)
    df = {t: sum(1 for c in docs.values() if t in c) for t in terms}
    k1, b = 1.5, 0.75
    scores = {}
    for slug, counts in docs.items():
        length = sum(counts.values())
        score = 0.0
        for t in terms:
            tf = counts.get(t, 0)
            if tf:
                idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg))
        if score:
            scores[slug] = score

    neighbours = defaultdict(set)
    for e in graph["edges"]:
        neighbours[e["source"]].add(e["target"])
        neighbours[e["target"]].add(e["source"])

    by_id = {n["id"]: n for n in graph["nodes"]}
    ranked = sorted(scores, key=lambda s: (-scores[s], s))[:k]
    return [{
        **by_id[slug],
        "score": round(scores[slug], 2),
        "neighbours": sorted(
            (by_id[x]["title"], by_id[x]["path"]) for x in neighbours[slug]
            if by_id[x]["kind"] == "topic"),
    } for slug in ranked]


def render_png(path, graph=None):
    """Draw the graph: one colour per section, node size by degree."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    graph = graph or load_graph()
    g = nx.Graph()
    for n in graph["nodes"]:
        g.add_node(n["id"], **n)
    for e in graph["edges"]:
        g.add_edge(e["source"], e["target"], kind=e["kind"])

    sections = sorted({n["title"] for n in graph["nodes"] if n["kind"] == "section"})
    cmap = plt.get_cmap("tab20")
    colour = {s: cmap(i % 20) for i, s in enumerate(sections)}
    section_of = {n["id"]: n["title"] if n["kind"] == "section" else n["section"]
                  for n in graph["nodes"]}

    pos = nx.spring_layout(g, k=0.35, iterations=120, seed=7)
    fig, ax = plt.subplots(figsize=(16, 12), dpi=150)
    fig.patch.set_facecolor("white")
    links = [(u, v) for u, v, d in g.edges(data=True) if d["kind"] == "links_to"]
    tree = [(u, v) for u, v, d in g.edges(data=True) if d["kind"] == "parent"]
    nx.draw_networkx_edges(g, pos, edgelist=tree, width=0.8, alpha=0.35,
                           edge_color="#555555", ax=ax)
    nx.draw_networkx_edges(g, pos, edgelist=links, width=0.4, alpha=0.18,
                           edge_color="#1f77b4", style="dashed", ax=ax)
    nx.draw_networkx_nodes(
        g, pos, ax=ax, linewidths=0.4, edgecolors="white",
        node_color=[colour.get(section_of[n], (0.6, 0.6, 0.6, 1)) for n in g],
        node_size=[40 + 18 * g.degree(n) if g.nodes[n]["kind"] == "topic" else 700
                   for n in g])
    ax.legend(handles=[plt.Line2D([], [], marker="o", ls="", color=colour[s], label=s,
                                  markersize=9) for s in sections],
              loc="lower left", frameon=False, fontsize=10, title="Help Center section")
    ax.set_title(f"KDP Help Center as a knowledge graph: "
                 f"{sum(1 for n in graph['nodes'] if n['kind'] == 'topic')} topics, "
                 f"{len(tree)} hierarchy edges, {len(links)} cross-references",
                 fontsize=14)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
