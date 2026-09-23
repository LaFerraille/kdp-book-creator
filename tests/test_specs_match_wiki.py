"""Guard against the knowledge base and the code drifting apart.

kdp_specs.yaml claims each of its constants comes from a particular help topic.
These tests check that claim literally: the number must still appear in that
file. When Amazon changes a specification and the mirror is refreshed, this
suite fails loudly instead of letting the project ship a book KDP will reject.

A failure here is not a bug in the test - it means KDP changed something and a
human needs to look at it.
"""
import re

import pytest

from kdp import specs
from kdp.wiki import TOPICS as WIKI

# The wiki is built on each machine, not committed. Where it is absent there is
# nothing to compare against; CI and contributors run `python -m kdp wiki build`.
pytestmark = pytest.mark.skipif(not WIKI.exists(), reason="the KDP wiki is not built")

# (dotted path into kdp_specs.yaml, topic file that documents it)
CITED_CONSTANTS = [
    ("interior.bleed", "set-trim-size-bleed-and-margins.md"),
    ("interior.min_font_pt", "paperback-fonts.md"),
    ("spine_factors_per_page.white", "create-a-paperback-cover.md"),
    ("spine_factors_per_page.cream", "create-a-paperback-cover.md"),
    ("spine_factors_per_page.groundwood", "paperback-submission-guidelines.md"),
    ("spine_factors_per_page.premium_color", "create-a-paperback-cover.md"),
    ("spine_factors_per_page.standard_color", "create-a-paperback-cover.md"),
    ("paperback_cover.bleed", "create-a-paperback-cover.md"),
    ("paperback_cover.spine_text_min_pages", "create-a-paperback-cover.md"),
    ("hardcover_cover.wrap", "create-a-hardcover-cover.md"),
    ("hardcover_cover.hinge", "create-a-hardcover-cover.md"),
    ("hardcover_cover.headband_min_pages", "create-a-hardcover-cover.md"),
    ("hardcover_cover.barcode_width", "create-a-hardcover-cover.md"),
    ("hardcover_cover.barcode_height", "create-a-hardcover-cover.md"),
    ("hardcover_cover.barcode_min_from_bottom", "create-a-hardcover-cover.md"),
    ("hardcover_cover.barcode_min_from_hinge", "create-a-hardcover-cover.md"),
    ("paperback_cover.spine_text_clearance", "create-a-paperback-cover.md"),
    ("paperback_cover.fold_variance", "create-a-paperback-cover.md"),
    ("file.max_size_mb", "paperback-submission-guidelines.md"),
    ("file.min_image_dpi", "paperback-submission-guidelines.md"),
]

# Constants KDP never states outright - we derive them from what it does state.
# A citation would be dishonest (the numeral might appear in an unrelated
# sentence and "pass" for the wrong reason), so each names the test that really
# proves it instead.
DERIVED_CONSTANTS = {
    # KDP publishes finished page sizes, not the split between the two axes.
    # test_geometry.py::test_bleed_matches_every_kdp_worked_example checks both
    # against all 29 worked examples, which is far stronger than a text match.
    "interior.bleed_added_to_width": "test_bleed_matches_every_kdp_worked_example",
    "interior.bleed_added_to_height": "test_bleed_matches_every_kdp_worked_example",
}


def _lookup(path):
    value = specs.constants()
    for part in path.split("."):
        value = value[part]
    return value


def _appears_in(value, text):
    """Is this number written in the topic, in any of KDP's formats?

    KDP writes 0.51 as both `0.51"` and `0.51”`, and 2.0 as `2"`, so compare on
    the numeral itself rather than on formatting.
    """
    literal = f"{value:g}"
    return bool(re.search(rf"(?<![\d.]){re.escape(literal)}(?![\d])", text))


@pytest.mark.parametrize("path,topic", CITED_CONSTANTS)
def test_constant_still_appears_in_its_cited_topic(path, topic):
    file = WIKI / topic
    assert file.exists(), f"cited topic missing from the mirror: {topic}"
    value = _lookup(path)
    text = file.read_text(encoding="utf-8")
    assert _appears_in(value, text), (
        f"{path} = {value} is no longer present in {topic}. "
        f"KDP may have changed this specification - verify against "
        f"https://kdp.amazon.com and update kdp_specs.yaml."
    )


def test_every_yaml_scalar_is_covered_by_a_citation():
    """New constants must arrive with a citation, or this test fails.

    Without this, someone adds a number to the YAML, no test references it, and
    the drift guarantee quietly stops covering the whole file.
    """
    cited = {p for p, _ in CITED_CONSTANTS} | set(DERIVED_CONSTANTS)
    uncited = []

    def walk(node, prefix=""):
        for key, value in node.items():
            if key.startswith("_") or key == "units":
                continue
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                walk(value, f"{path}.")
            elif isinstance(value, (int, float)) and path not in cited:
                uncited.append(path)

    walk(specs.constants())
    assert not uncited, (
        f"these constants have no citation: {uncited}. Add each to "
        f"CITED_CONSTANTS with the topic documenting it, or to DERIVED_CONSTANTS "
        f"naming the test that proves it. Otherwise the drift check silently "
        f"stops covering the whole file."
    )


def test_trim_tables_are_present_and_plausible():
    paperback = specs.trim_sizes("paperback", "com")
    hardcover = specs.trim_sizes("hardcover", "com")
    assert len(paperback) >= 15, "US paperback trim sizes look truncated"
    assert len(hardcover) >= 5, "US hardcover trim sizes look truncated"

    # 6x9 is KDP's most common size and must always be offered.
    assert any(t["width"] == 6.0 and t["height"] == 9.0 for t in paperback)

    for t in paperback:
        white = t["papers"]["white"]
        assert white and white["min"] < white["max"]


def test_margin_brackets_are_contiguous_and_ascending():
    """Gaps between brackets would make some page counts unresolvable."""
    brackets = specs.margins()
    assert len(brackets) == 5
    for previous, current in zip(brackets, brackets[1:], strict=False):
        assert current["min_pages"] == previous["max_pages"] + 1, "gap between brackets"
        assert current["gutter"] > previous["gutter"], "gutter must grow with thickness"
