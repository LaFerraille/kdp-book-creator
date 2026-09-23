"""The one tokenizer both output formats share.

It lives in one module so that a fix to what counts as emphasis lands in the
PDF and the EPUB at the same time. These tests check the spans themselves;
test_latex.py and test_epub.py check what each format makes of them.
"""
import pytest

from kdp import inline


def spans(text):
    """Every span the tokenizer finds, as (kind, value), with plain runs out."""
    found = []

    def emit(kind, value, _match):
        found.append((kind, value))
        return ""

    inline.render(text, lambda plain: "", emit)
    return found


@pytest.mark.parametrize("text,expected", [
    ("**loud**", [("bold", "loud")]),
    ("*soft*", [("italic", "soft")]),
    ("***both***", [("bolditalic", "both")]),
    ("`code`", [("code", "code")]),
    (r"\*", [("escaped", "*")]),
    ("[text](url)", [("link", "text")]),
])
def test_each_kind_of_span_is_recognised(text, expected):
    assert spans(text) == expected


def test_three_markers_are_read_as_one_span_not_two():
    """`***x***` as bold-then-stray-pair printed the leftover asterisks.

    The order in the pattern is what decides this, and the Word reader is what
    produces the input: a run carrying both <w:b/> and <w:i/> converts to
    exactly this.
    """
    assert spans("a ***b*** c") == [("bolditalic", "b")]


def test_an_escape_wins_over_the_markup_it_escapes():
    r"""`\*` is a literal asterisk, and printing the backslash put a stray mark
    in the middle of a sentence in a finished book."""
    assert spans(r"3 \* 4") == [("escaped", "*")]


@pytest.mark.parametrize("text", ["2 * 3 = 6", "a * b * c", "* "])
def test_a_marker_that_does_not_hug_its_content_is_not_markup(text):
    """Arithmetic in prose is not emphasis."""
    assert spans(text) == []


def test_adjacent_spans_are_kept_apart():
    assert spans("**a** and *b*") == [("bold", "a"), ("italic", "b")]


def test_a_link_keeps_its_url_on_the_match():
    """The print renderer drops it and the ebook keeps it, so both need it."""
    found = []
    inline.render("see [here](https://example.com)", lambda p: p,
                  lambda kind, value, match: found.append(match.group("link_url")) or "")
    assert found == ["https://example.com"]


def test_plain_text_passes_through_the_escape_function():
    """Everything outside a span must be escaped, or a `$` opens math mode."""
    assert inline.render("a $ b", lambda plain: plain.replace("$", "\\$"),
                         lambda *_: "") == "a \\$ b"


def test_every_named_kind_is_reachable():
    """A group in the pattern that KINDS does not list is emitted as a link."""
    named = set(inline.PATTERN.groupindex) - {"link_text", "link_url"}
    assert named == set(inline.KINDS)
