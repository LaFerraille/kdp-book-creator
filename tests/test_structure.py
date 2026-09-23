"""Recovering chapters from a manuscript whose structure is a convention.

A plain .txt carries its structure the way a printed book does - a title
underlined, a line reading "ACT 1" - and a parser that only knows `#` sees one
undifferentiated block. That still renders, which is the danger: a PDF with no
chapter breaks and an EPUB with an empty spine both look like success.
"""
import pytest

from kdp import structure


def titles(inference):
    return [(level, title) for level, title in inference.headings]


# --- setext --------------------------------------------------------------
def test_underlined_titles_become_headings():
    result = structure.infer(
        "Hamlet\n======\n\nText.\n\nScene 1\n-------\n\nMore text.\n")
    assert titles(result) == [(1, "Hamlet"), (2, "Scene 1")]
    assert "# Hamlet" in result.text
    assert "## Scene 1" in result.text


def test_the_underline_itself_is_consumed():
    """Left in, a row of equals signs sets as a paragraph under the title."""
    result = structure.infer("Hamlet\n======\n\nText.\n")
    assert "======" not in result.text


def test_a_short_rule_is_not_an_underline():
    """A row of dashes used as a scene break must not promote the line above."""
    result = structure.infer("A long sentence ending a scene.\n---\n\nNext.\n")
    assert not result.found


def test_a_long_line_is_not_a_section_title():
    long = "This is a whole sentence of prose that happens to be followed by dashes"
    result = structure.infer(f"{long}\n{'-' * len(long)}\n\nText.\n")
    assert not result.found


# --- labelled divisions --------------------------------------------------
def test_standalone_division_lines_become_headings():
    result = structure.infer("Chapter 1\n\nText.\n\nChapter 2\n\nMore.\n")
    assert titles(result) == [(1, "Chapter 1"), (1, "Chapter 2")]


def test_a_sentence_that_merely_starts_with_a_division_word_is_left_alone():
    result = structure.infer(
        "Chapter 4 was the hardest of them all, and he said so often.\n")
    assert not result.found


def test_the_inner_family_of_a_play_is_demoted():
    """Flat, a play reads as twenty-six chapters where there are five acts."""
    text = ("Act 1\n\nText.\n\nScene 1\n\nText.\n\nScene 2\n\nText.\n\n"
            "Act 2\n\nText.\n\nScene 1\n\nText.\n")
    result = structure.infer(text)
    assert titles(result) == [(1, "Act 1"), (2, "Scene 1"), (2, "Scene 2"),
                              (1, "Act 2"), (2, "Scene 1")]


def test_a_single_family_is_left_flat():
    result = structure.infer("Chapter 1\n\nText.\n\nChapter 2\n\nMore.\n")
    assert {level for level, _ in result.headings} == {1}


@pytest.mark.parametrize("word", ["chapitre", "kapitel", "capitolo", "partie",
                                  "prologue", "escena"])
def test_divisions_are_recognised_in_the_languages_this_tool_supports(word):
    result = structure.infer(f"{word.title()} 1\n\nText.\n\n{word.title()} 2\n\nMore.\n")
    assert len(result.headings) == 2


# --- reporting -----------------------------------------------------------
def test_nothing_recognisable_is_said_plainly():
    result = structure.infer("Just prose.\n\nMore prose.\n")
    assert not result.found
    assert result.text == "Just prose.\n\nMore prose.\n"
    assert "No chapter structure" in result.summary()


def test_the_summary_names_the_convention_it_used():
    """Inference is a proposal, so it has to be explicable to be confirmable."""
    result = structure.infer("Hamlet\n======\n\nText.\n")
    assert "1 chapter" in result.summary()
    assert "underlined titles" in result.summary()
