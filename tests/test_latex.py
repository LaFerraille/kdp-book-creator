"""Escaping bugs corrupt a book silently, so they get their own suite.

An unescaped `$` does not crash the build - it opens math mode, and the rest of
the paragraph comes out in italics with the spaces eaten. The example manuscript
contains exactly that character, in "1 EUR pour 200 $".
"""
import pytest

from kdp.latex import escape, inline_to_latex


# --- raw escaping --------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("100 %", r"100 \%"),
    ("200 $", r"200 \$"),
    ("Tom & Jerry", r"Tom \& Jerry"),
    ("chapter #3", r"chapter \#3"),
    ("snake_case", r"snake\_case"),
    ("{braced}", r"\{braced\}"),
    ("a~b", r"a\textasciitilde{}b"),
    ("2^10", r"2\textasciicircum{}10"),
    ("back\\slash", r"back\textbackslash{}slash"),
])
def test_escapes_every_latex_special(raw, expected):
    assert escape(raw) == expected


def test_accents_and_guillemets_pass_through_untouched():
    """XeLaTeX reads UTF-8 natively; mangling these would be the bug."""
    text = "« Bonjour, ça va ? » — l'été, où ça ? Œuvre, naïf, 15 €"
    assert escape(text) == text


def test_escaping_is_not_double_applied():
    once = escape("50 % & more")
    assert escape.__doc__  # sanity: the function is documented
    assert once == r"50 \% \& more"
    assert "\\\\" not in once


# --- inline markdown -----------------------------------------------------
def test_italic_becomes_textit():
    assert inline_to_latex("un mot *brouillé* ici") == r"un mot \textit{brouillé} ici"


def test_bold_becomes_textbf():
    assert inline_to_latex("**très** important") == r"\textbf{très} important"


def test_bold_wins_over_italic_when_nested_markers_collide():
    assert inline_to_latex("**gras**") == r"\textbf{gras}"


def test_code_becomes_texttt():
    assert inline_to_latex("run `make all` now") == r"run \texttt{make all} now"


def test_specials_inside_emphasis_are_still_escaped():
    """The dangerous case: markup handled but its contents left raw."""
    assert inline_to_latex("*100 % sûr*") == r"\textit{100 \% sûr}"


def test_specials_outside_emphasis_are_escaped():
    assert inline_to_latex("200 $ et *jamón*") == r"200 \$ et \textit{jamón}"


def test_link_keeps_its_text():
    assert inline_to_latex("see [the docs](https://x.com)") == "see the docs"


def test_lone_asterisk_is_not_treated_as_emphasis():
    """An unpaired marker must not swallow the rest of the paragraph."""
    out = inline_to_latex("2 * 3 = 6")
    assert "textit" not in out
    assert "2" in out and "6" in out


def test_a_sentence_mixing_italics_and_currency():
    raw = "paie ses *croissants* en euros et ses livres en dollars (1 € pour 200 $)"
    out = inline_to_latex(raw)
    assert r"\textit{croissants}" in out
    assert r"200 \$" in out
    assert "€" in out


def test_italic_command_can_be_swapped_for_foreign_phrases():
    """A book whose italics mark foreign words needs hyphenation suppressed."""
    out = inline_to_latex("un mot *castellano* ici", italic_command="foreignphrase")
    assert out == r"un mot \foreignphrase{castellano} ici"


def test_swapping_the_italic_command_leaves_bold_and_code_alone():
    out = inline_to_latex("**gras** et `code`", italic_command="foreignphrase")
    assert r"\textbf{gras}" in out and r"\texttt{code}" in out


# --- backslash escapes ---------------------------------------------------
def test_an_escaped_metacharacter_prints_without_its_backslash():
    """A literal "\\*" used to put a stray backslash in the finished book."""
    assert inline_to_latex(r"un prix de 5\* et \[crochets\]") == "un prix de 5* et [crochets]"


def test_an_escape_beats_emphasis():
    """Escaped markers are characters, not markup."""
    assert r"\textit" not in inline_to_latex(r"\*not italic\*")
