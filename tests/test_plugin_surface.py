"""The plugin's own files are part of the product and can rot silently.

book_defaults.yaml in particular: it is prose-adjacent, and a trim
size that KDP stops offering would sit there proposing an unbuildable book.
"""
import json
import pathlib

import pytest
import yaml

from kdp import specs
from kdp.bookspec import PAPERS, BookSpec

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "kdp-formatting"
COMMANDS = ["kdp-book", "kdp-cover", "kdp-check", "kdp-wiki", "kdp-chat"]

DEFAULTS = specs.book_defaults()


def test_plugin_manifest_is_valid_json_with_the_required_fields():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "kdp-book-creator"
    assert manifest["description"]


def test_skill_has_frontmatter_with_name_and_description():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---")[1])
    assert front["name"] == "kdp-formatting"
    assert front["description"].startswith("Use when")
    assert len(text.split("---")[1]) < 1024


def test_skill_description_states_triggers_not_workflow():
    """A description that summarises the workflow gets followed instead of the
    skill body, so the body becomes documentation nobody reads."""
    front = yaml.safe_load((SKILL / "SKILL.md").read_text(encoding="utf-8").split("---")[1])
    description = front["description"].lower()
    for workflow_word in ("first", "then", "step", "stage", "finally", "after that"):
        assert workflow_word not in description, f"description narrates workflow: {workflow_word!r}"


def test_every_referenced_file_exists():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for name in ("references/kdp-lookup.md", "references/interview.md"):
        assert name in text, f"{name} is never referenced"
        assert (SKILL / name).exists(), f"{name} is referenced but missing"


# --- defaults must stay buildable ----------------------------------------
@pytest.mark.parametrize("book_type", list(DEFAULTS))
def test_every_default_is_a_real_kdp_trim_and_paper_combination(book_type):
    values = DEFAULTS[book_type]
    spec = BookSpec(
        trim_w=values["trim"][0], trim_h=values["trim"][1], paper=values["paper"],
        font_pt=values["font_pt"],
    )
    problems = spec.validate()
    assert problems == [], f"{book_type}: {problems}"


@pytest.mark.parametrize("book_type", list(DEFAULTS))
def test_every_default_key_is_a_real_bookspec_field(book_type):
    """Otherwise a default silently does nothing when the interview applies it."""
    fields = set(BookSpec.__dataclass_fields__)
    for key in DEFAULTS[book_type]:
        if key.endswith("_reason") or key == "trim":
            continue
        assert key in fields, f"{book_type}.{key} is not a BookSpec field"


@pytest.mark.parametrize("book_type", list(DEFAULTS))
def test_every_default_paper_is_a_known_stock(book_type):
    assert DEFAULTS[book_type]["paper"] in PAPERS


def test_defaults_cover_the_book_types_the_interview_offers():
    """Compared on letters only: the interview writes "children's" where the
    defaults key is `childrens`, and that difference is not a real mismatch."""
    import re
    interview = re.sub(r"[^a-z]", "", (SKILL / "references" / "interview.md")
                       .read_text(encoding="utf-8").lower())
    for book_type in DEFAULTS:
        stem = book_type.split("_")[0]
        assert stem in interview, f"{book_type} has defaults but the interview never offers it"


# --- commands ------------------------------------------------------------
@pytest.mark.parametrize("name", COMMANDS)
def test_command_has_frontmatter_and_a_description(name):
    text = (ROOT / "commands" / f"{name}.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---")[1])
    assert front.get("description")


def test_commands_point_at_the_skill():
    for name in COMMANDS:
        text = (ROOT / "commands" / f"{name}.md").read_text(encoding="utf-8")
        assert "kdp-formatting" in text, f"{name} never invokes the skill"


# --- lookup table --------------------------------------------------------
def test_every_topic_in_the_lookup_table_exists_in_the_mirror():
    """A lookup table pointing at a topic that was renamed is worse than none."""
    import re

    from kdp.wiki import TOPICS as topics
    if not topics.exists():
        pytest.skip("the KDP wiki is not built on this machine")
    text = (SKILL / "references" / "kdp-lookup.md").read_text(encoding="utf-8")
    missing = [m for m in re.findall(r"`([a-z0-9-]+\.md)`", text) if not (topics / m).exists()]
    assert missing == [], f"lookup table points at missing topics: {missing}"


# --- the docs must name commands that exist ------------------------------
def _shipped_docs():
    """Docs that ship with the plugin."""
    return (list((ROOT / "commands").glob("*.md")) + list((ROOT / "skills").rglob("*.md"))
            + list((ROOT / "docs").glob("*.md"))
            + [ROOT / "README.md", ROOT / "CONTRIBUTING.md"])


def test_every_cli_invocation_in_the_docs_actually_runs():
    """The whole documented surface was once unrunnable and nothing noticed.

    Every command doc, SKILL.md and the README told the reader to run
    `uv run python -m kdp.cli ...`, which raised ModuleNotFoundError, while
    interview.md used a bare `kdp ...` console script that did not exist. Both
    were wrong for months because the suite checked that the docs mentioned the
    skill, never that what they told you to type would work.
    """
    import re

    docs = _shipped_docs()

    invocations = set()
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:^|[`\s/])kdp ([a-z]+)\b", text, re.M):
            invocations.add((doc.name, match.group(1)))

    assert invocations, "no documented kdp invocations found - has the form changed?"

    known = {"analyse", "analyze", "build", "find", "cover", "doctor", "check", "wiki"}
    wrong = sorted(f"{doc}: kdp {sub}" for doc, sub in invocations if sub not in known)
    assert not wrong, f"documented commands that do not exist: {wrong}"


def test_no_doc_still_uses_an_invocation_that_does_not_exist():
    """Both dead forms: the old module path, and the console script.

    There is no console script any more - installing this package is what the
    root layout exists to avoid - so `uv run kdp` would fail just as surely as
    `python -m kdp.cli` once did.
    """
    dead = ("python -m kdp.cli", "uv run kdp", "uv sync")
    offenders = []
    for doc in _shipped_docs():
        text = doc.read_text(encoding="utf-8")
        for form in dead:
            if form in text:
                offenders.append(f"{doc.name}: {form}")
    assert not offenders, f"documented invocations that do not work: {offenders}"


# --- the docs must quote numbers the code actually produces --------------
def _blank_pdf(path, pages=1, width=396.0, height=612.0):
    """The smallest thing preflight will accept and count checks on."""
    import pikepdf
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(width, height))
    pdf.save(path)
    return path


def _check_counts(tmp_path):
    """How many checks each preflight actually emits, counted rather than quoted."""
    from kdp.geometry import CoverGeometry
    from kdp.preflight import preflight_cover, preflight_interior

    spec = BookSpec(trim_w=5.5, trim_h=8.5, paper="cream")
    interior = preflight_interior(_blank_pdf(tmp_path / "interior.pdf"), spec,
                                  overfull=())

    geometry = CoverGeometry.paperback(5.5, 8.5, 314, "cream")
    cover_pdf = _blank_pdf(tmp_path / "cover.pdf",
                           width=geometry.width * 72, height=geometry.height * 72)
    cover = preflight_cover(cover_pdf, geometry)
    return len(interior.checks), len(cover.checks)


def test_the_docs_quote_the_number_of_checks_preflight_really_runs(tmp_path):
    """The README sells these counts under "what it guarantees".

    It once claimed 13 and 10 against a real 14 and 11. Numbers in the one
    place the docs make a safety claim have to come from the code.
    """
    interior, cover = _check_counts(tmp_path)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"**Interior, {interior} checks**" in readme
    assert f"**Cover, {cover} checks**" in readme


def test_every_path_the_docs_point_at_exists():
    """"Reproducing this" told the reader to run a file that is git-ignored."""
    import re

    missing = []
    for doc in _shipped_docs():
        text = doc.read_text(encoding="utf-8")
        for match in re.finditer(r"\bkdp \w+ ([\w./-]+\.\w+)", text):
            target = match.group(1)
            # A bare file name is a placeholder standing for the reader's own
            # manuscript ("manuscript.md", "some.pdf"). A path is a claim
            # about this repository, and is what can go stale.
            if "/" not in target:
                continue
            if not (ROOT / target).exists():
                missing.append(f"{doc.name}: {target}")
    assert not missing, f"docs point at files that do not exist: {missing}"


# --- marketplace ---------------------------------------------------------
def test_the_repo_is_a_marketplace_offering_this_plugin():
    """`/plugin marketplace add` reads this file; the plugin entry must resolve
    to the repository root, where plugin.json lives."""
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert market["name"] and market["owner"]["name"]
    [entry] = market["plugins"]
    assert entry["name"] == plugin["name"]
    assert (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").exists()
