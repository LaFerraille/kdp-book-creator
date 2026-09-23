"""The KDP knowledge base: a local mirror of the KDP Help Center, as a graph.

    fetch.py   help centre -> wiki/.cache/*.html   (resumable, polite)
    build.py   .cache -> wiki/topics/*.md, INDEX.md, index.json
    graph.py   topics -> wiki/graph.json, keyword search, PNG rendering
    specs.py   the trim-size and margin tables -> kdp/specs/trim_sizes.json

Nothing here is committed: the content is Amazon's, so each user builds it on
their own machine with `kdp wiki build`.
"""
import pathlib
import re

WIKI = pathlib.Path(__file__).resolve().parents[2] / "wiki"
CACHE = WIKI / ".cache"
TOPICS = WIKI / "topics"
GRAPH = WIKI / "graph.json"

# Topics are linked two different ways: the navigation tree uses
# /help/topic/<ID>, while in-body cross references use /help?topicId=<ID>.
# Some topics only ever appear in the second form, so match both.
TOPIC_RE = re.compile(r"(?:/help/topic/|topicId=)([A-Z0-9]{8,})")
