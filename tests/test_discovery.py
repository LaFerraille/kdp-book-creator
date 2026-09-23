"""Discovery measures what is countable; agents judge the rest.

These tests cover the measured half only. The agent half is non-deterministic
by nature and is exercised end-to-end against the example manuscript instead.
"""
import pathlib

from kdp.discovery import discover, propose_rules
from kdp.ingest import load_manuscript, parse_markdown

EXAMPLE = pathlib.Path(__file__).resolve().parent / "fixtures" / "novel-fr.md"


def test_detects_guillemets_dialogue():
    md = '# C\n\n## S\n\n' + "\n\n".join(
        f"Il dit « bonjour numéro {i} » et repartit." for i in range(8)
    )
    r = discover(parse_markdown(md))
    assert r.typography.dialogue_style == "guillemets"
    assert r.typography.dialogue_count >= 8


def test_detects_double_quote_dialogue():
    md = '# C\n\n## S\n\n' + "\n\n".join(
        f"He said “hello number {i}” and left." for i in range(8)
    )
    r = discover(parse_markdown(md))
    assert r.typography.dialogue_style == "double_quotes"


def test_ignores_dialogue_style_below_the_noise_floor():
    """Two stray quote marks are not a convention."""
    r = discover(parse_markdown('# C\n\n## S\n\nIl dit « oui ». Puis « non ».\n'))
    assert r.typography.dialogue_style is None


def test_counts_emphasis_but_not_strong_as_italic():
    r = discover(parse_markdown("# C\n\n## S\n\nUn *mot* et un **autre** ici.\n"))
    assert r.typography.emphasis_count == 1
    assert r.typography.strong_count == 1


def test_measures_paragraph_length():
    short = discover(parse_markdown("# C\n\n## S\n\n" + "word " * 10))
    long = discover(parse_markdown("# C\n\n## S\n\n" + "word " * 300))
    assert long.typography.avg_paragraph_words > short.typography.avg_paragraph_words


def test_excerpts_are_deterministic_for_a_given_seed():
    """Two runs must hand an agent the same evidence, or proposals wobble."""
    book = parse_markdown(
        "# C\n\n## S\n\n" + "\n\n".join("mot " * 60 + f"fin {i}." for i in range(30))
    )
    assert discover(book, seed=7).excerpts == discover(book, seed=7).excerpts


def test_flags_a_chapter_far_shorter_than_the_rest():
    md = "".join(f"# Chapter {i}\n\n## S\n\n{'word ' * 500}\n\n" for i in range(1, 5))
    md += "# Chapter 5\n\n## S\n\ntiny.\n"
    r = discover(parse_markdown(md))
    assert any("shorter than average" in a for a in r.anomalies)


# --- proposed rules ------------------------------------------------------
def test_rules_carry_a_reason_and_are_never_bare_verdicts():
    """The interview has to justify itself, not issue settings."""
    r = discover(load_manuscript(EXAMPLE))
    rules = propose_rules(r)
    assert rules
    for rule in rules:
        assert rule.reason and len(rule.reason) > 20, f"{rule.key} has no usable reason"


def test_self_numbered_titles_produce_a_no_numbering_rule():
    r = discover(load_manuscript(EXAMPLE))
    keys = {rule.key: rule.value for rule in propose_rules(r)}
    assert keys["number_chapters"] is False
    assert keys["number_sections"] is False


def test_image_free_manuscript_is_proposed_black_and_white():
    r = discover(load_manuscript(EXAMPLE))
    keys = {rule.key: rule.value for rule in propose_rules(r)}
    assert keys["interior_ink"] == "black & white"


def test_real_manuscript_summary_is_complete():
    r = discover(load_manuscript(EXAMPLE), raw_text=EXAMPLE.read_text(encoding="utf-8"))
    text = "\n".join(r.summary_lines())
    assert "3 chapters" in text
    assert "fr" in text
    assert r.structure.heading_pattern == "# chapter > ### subtitle > ## section"


# --- normalisation -------------------------------------------------------
def test_normalises_inconsistent_zero_padding():
    book = parse_markdown(
        "# Chapitre 1\n\nx\n\n# Chapitre 07\n\ny\n\n# Chapitre 8\n\nz\n"
    )
    from kdp.discovery import normalize_chapter_numbers
    changes = normalize_chapter_numbers(book)
    assert changes == [("Chapitre 07", "Chapitre 7")]
    assert [c.title for c in book.chapters] == ["Chapitre 1", "Chapitre 7", "Chapitre 8"]


def test_consistent_padding_is_left_alone():
    """If every chapter is padded, that is a style, not a mistake."""
    from kdp.discovery import normalize_chapter_numbers
    book = parse_markdown("# Chapitre 01\n\nx\n\n# Chapitre 02\n\ny\n")
    assert normalize_chapter_numbers(book) == []
    assert book.chapters[0].title == "Chapitre 01"


def test_normalisation_does_not_touch_years_or_other_numbers():
    from kdp.discovery import normalize_chapter_numbers
    book = parse_markdown("# Chapitre 07\n\nx\n\n# Chapitre 8 — 2025\n\ny\n")
    normalize_chapter_numbers(book)
    assert book.chapters[1].title == "Chapitre 8 — 2025"
