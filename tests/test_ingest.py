"""Ingest turns any supported input into one Book IR.

The heading heuristics carry the most risk: get them wrong and a chapter
subtitle becomes a section, or fifteen chapters collapse into one.
"""

import pytest

from kdp.ingest import detect_language, load_manuscript, parse_markdown
from kdp.ir import BlockQuote, Image, Lines, ListBlock, Paragraph, Rule


# --- basic block parsing -------------------------------------------------
def test_parses_chapters_sections_and_paragraphs():
    md = """# Chapter One

Opening paragraph.

## First Section

Body text here.

## Second Section

More body.

# Chapter Two

Another opening.
"""
    book = parse_markdown(md)
    assert [c.title for c in book.chapters] == ["Chapter One", "Chapter Two"]
    assert [s.title for s in book.chapters[0].sections] == ["First Section", "Second Section"]
    assert book.chapters[0].preamble == [Paragraph("Opening paragraph.")]
    assert book.chapters[0].sections[0].blocks == [Paragraph("Body text here.")]


def test_paragraphs_join_wrapped_lines():
    book = parse_markdown("# C\n\nA line\nwrapped across two.\n")
    assert book.chapters[0].preamble == [Paragraph("A line wrapped across two.")]


def test_images_are_captured_as_blocks():
    book = parse_markdown("# C\n\n![A caption](pic.png)\n")
    assert book.chapters[0].preamble == [Image(path="pic.png", alt="A caption")]


# --- the heading heuristic that matters ----------------------------------
def test_h3_directly_under_h1_is_a_chapter_subtitle_not_a_section():
    """The example manuscript's actual shape.

    `#` chapter, `###` date line beneath it, then `##` sections. Treating the
    `###` as a subsection would nest all four sections under a phantom heading
    and put the date in the table of contents.
    """
    md = """# Chapitre 1 - La boutique de la rue
### Automne - hiver

## I. L'enseigne

Du texte.
"""
    book = parse_markdown(md)
    chapter = book.chapters[0]
    assert chapter.title == "Chapitre 1 - La boutique de la rue"
    assert chapter.subtitle == "Automne - hiver"
    assert [s.title for s in chapter.sections] == ["I. L'enseigne"]


def test_h3_after_body_text_is_a_real_subsection_not_a_subtitle():
    """Only an h3 that *immediately* follows the chapter heading is a subtitle."""
    md = """# Chapter

Some body text first.

### Not A Subtitle

More text.
"""
    book = parse_markdown(md)
    assert book.chapters[0].subtitle is None


def test_content_before_any_heading_is_kept():
    """Text with no chapter heading must not be silently dropped."""
    book = parse_markdown("Loose opening text.\n\n# Chapter\n\nBody.\n")
    assert book.orphan_blocks == [Paragraph("Loose opening text.")]


# --- language detection --------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Le chat est sur la table et il ne veut pas descendre de la chaise", "fr"),
    ("The cat is on the table and it will not come down from the chair", "en"),
    ("El gato esta en la mesa y no quiere bajar de la silla que tiene", "es"),
])
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_detect_language_returns_none_when_unsure():
    assert detect_language("xyzzy plugh frobnicate") is None


# --- self-numbered titles ------------------------------------------------
@pytest.mark.parametrize("titles,expected", [
    (["Chapitre 1 — La boutique", "Chapitre 2 — Le papier"], True),
    (["Chapter 1", "Chapter 2", "Chapter 3"], True),
    (["1. Beginnings", "2. Middles"], True),
    (["I. L'enseigne", "II. Le premier client"], True),
    (["Beginnings", "Middles", "Ends"], False),
    (["The 39 Steps", "Catch 22"], False),
])
def test_detects_titles_that_carry_their_own_numbering(titles, expected):
    """If they do, the typesetter must not add a second number."""
    from kdp.ingest import _titles_are_self_numbered
    assert _titles_are_self_numbered(titles) is expected


def test_a_single_unnumbered_prologue_does_not_flip_the_verdict():
    from kdp.ingest import _titles_are_self_numbered
    assert _titles_are_self_numbered(
        ["Prologue", "Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"]
    ) is True


def test_chapters_and_sections_are_judged_separately():
    """A book may number one level and not the other."""
    from kdp.ingest import chapters_are_self_numbered, sections_are_self_numbered
    book = parse_markdown(
        "# Chapter 1\n\n## Opening\n\nx\n\n# Chapter 2\n\n## Closing\n\ny\n"
    )
    assert chapters_are_self_numbered(book) is True
    assert sections_are_self_numbered(book) is False


# --- verse and other blocks whose line breaks matter ---------------------
def test_verse_keeps_its_lines():
    """Reflowing verse into a paragraph destroys the thing it is."""
    from kdp.ir import Lines
    book = parse_markdown(
        "# Poem\n\n"
        "Doubt thou the stars are fire,\n"
        "Doubt that the sun doth move,\n"
        "Doubt truth to be a liar,\n"
        "But never doubt I love.\n"
    )
    blocks = list(book.all_blocks())
    verse = [b for b in blocks if isinstance(b, Lines)]
    assert len(verse) == 1
    assert len(verse[0].lines) == 4
    assert verse[0].lines[0] == "Doubt thou the stars are fire,"


def test_hard_wrapped_prose_is_still_joined():
    """The risk of preserving line breaks is doing it to a novel."""
    from kdp.ir import Lines, Paragraph
    book = parse_markdown(
        "# Chapter\n\n"
        "The ferry left at six, and by a quarter past the harbour lights were\n"
        "no more than a smudge behind the rain. Nobody on deck said a word\n"
        "until the engine settled into the long, even note of open water.\n"
    )
    blocks = list(book.all_blocks())
    assert not [b for b in blocks if isinstance(b, Lines)]
    assert any(isinstance(b, Paragraph) for b in blocks)


def test_a_wrapped_bracketed_aside_is_not_verse():
    """A stage direction wrapped by the source file is not a poem."""
    from kdp.ir import Lines
    book = parse_markdown(
        "# Scene\n\n"
        "[Flourish. Enter Claudius, King of Denmark,\n"
        "Gertrude the Queen, and Polonius.]\n"
    )
    assert not [b for b in book.all_blocks() if isinstance(b, Lines)]


# --- the book's own title ------------------------------------------------
def test_front_matter_supplies_title_and_author():
    from kdp.ingest import title_from
    found = title_from("---\ntitle: The Salt Road\nauthor: A. Rivers\n---\n\n# One\n\nText.\n")
    assert found["title"] == "The Salt Road"
    assert found["author"] == "A. Rivers"


def test_a_lone_heading_above_the_chapters_is_a_title_page():
    from kdp.ingest import title_from
    assert title_from("# The Salt Road\n\n# One\n\nText.\n")["title"] == "The Salt Road"


def test_a_chapter_heading_is_never_taken_as_the_title():
    """Doing so produced a memoir titled after its own last chapter."""
    from kdp.ingest import title_from
    assert title_from("# One\n\nIt began badly.\n\n# Two\n\nMore.\n") == {}
    assert title_from("# Chapter 1\n\n# Chapter 2\n\nText.\n") == {}


def test_a_chapter_with_a_subtitle_is_not_a_title_page():
    """`# Chapter` followed straight by `### date` is every chapter's shape."""
    from kdp.ingest import title_from
    md = "# Chapitre 1 — La boutique\n### Automne\n\n## I. L'enseigne\n\nTexte.\n"
    assert title_from(md) == {}


# --- every block type must be handled everywhere -------------------------
# One representative of each leaf block, maintained by hand. The test below
# asserts this covers every leaf block the IR defines, so adding a block type
# to ir.py fails here until it is added to this table - and, through it, to
# the word count and to both renderers.
SAMPLES = {
    Paragraph: Paragraph("Two words here."),
    BlockQuote: BlockQuote("A quoted line."),
    Lines: Lines(("To be, or not to be,", "that is the question.")),
    ListBlock: ListBlock(("first item", "second item")),
    Image: Image(path="plate.png", alt="A plate"),
    Rule: Rule(),
}


def _leaf_blocks():
    """Every leaf block type in the IR, found rather than listed.

    The leaf blocks are the frozen dataclasses; Chapter, Section, Book and the
    metadata records are mutable. Deriving the set means this cannot go stale.
    """
    import dataclasses

    from kdp import ir
    return {value for value in vars(ir).values()
            if dataclasses.is_dataclass(value)
            and value.__dataclass_params__.frozen}


def test_the_sample_table_covers_every_block_type_in_the_ir():
    assert set(SAMPLES) == _leaf_blocks()


def test_every_block_type_has_a_word_count():
    """Lines was added to the IR and to every renderer, and missed here.

    A play in verse then reported 10,049 words against an actual 32,004 - a
    threefold undercount, which made `analyse` promise 36 pages for a book that
    renders to 203. Nothing failed; the number was simply wrong.
    """
    from kdp.ingest import _WORDS_IN
    assert set(_WORDS_IN) == _leaf_blocks()


def test_verse_lines_are_counted_as_words():
    from kdp.ingest import _count_words
    assert _count_words(SAMPLES[Lines]) == 10


def test_a_book_of_verse_does_not_report_zero_words():
    book = parse_markdown(
        "# Act 1\n\n"
        "To be, or not to be,\n"
        "that is the question:\n"
        "Whether tis nobler in the mind\n"
    )
    assert isinstance(next(book.all_blocks()), Lines)
    assert book.stats.words == 16


@pytest.mark.parametrize("block_type", sorted(SAMPLES, key=lambda t: t.__name__))
def test_every_block_type_renders_in_both_formats(block_type):
    """The same drift, one layer on: a renderer that silently emits nothing."""
    from kdp.render_epub import _block_to_html
    from kdp.render_print import _render_block
    assert _render_block(SAMPLES[block_type]).strip()
    assert _block_to_html(SAMPLES[block_type], False).strip()


# --- encodings -----------------------------------------------------------
def test_a_utf16_file_is_read_as_utf16(tmp_path):
    """It decoded as cp1252 into NUL-riddled mojibake and did not fail.

    `analyse` read the result and reported "951 words, Language: pt (high
    confidence)". latin-1 accepts any byte at all, so the fallback chain can
    never discover this on its own - the byte-order mark has to be consulted
    first.
    """
    from kdp.ingest import read_text
    path = tmp_path / "book.txt"
    path.write_bytes("# Chapitre 1\n\nIl est parti sur la route.\n".encode("utf-16"))

    text, encoding = read_text(path)
    assert encoding == "utf-16"
    assert "\x00" not in text
    assert text.startswith("# Chapitre 1")


def test_a_utf16_file_without_a_byte_order_mark_is_still_recognised(tmp_path):
    """The NUL between every letter is the tell, and prose contains none."""
    from kdp.ingest import read_text
    path = tmp_path / "book.txt"
    path.write_bytes("# One\n\nSome plain English prose.\n".encode("utf-16-le"))

    text, encoding = read_text(path)
    assert encoding == "utf-16-le"
    assert "\x00" not in text


def test_a_utf8_byte_order_mark_does_not_become_part_of_the_title(tmp_path):
    from kdp.ingest import read_text
    path = tmp_path / "book.txt"
    path.write_bytes(b"\xef\xbb\xbf# One\n\nText.\n")
    text, _ = read_text(path)
    assert text.startswith("# One")


def test_windows_line_endings_do_not_hide_the_front_matter(tmp_path):
    """A manuscript saved on Windows ends every line with CRLF.

    The front-matter pattern expects a bare newline after the fence, so the
    title went unread and "title: ... author: ..." was set as the first
    paragraph of the book.
    """
    path = tmp_path / "book.md"
    path.write_bytes(b"---\r\ntitle: Salt\r\nauthor: A. Rivers\r\n---\r\n\r\n"
                     b"# One\r\n\r\nText.\r\n")
    book = load_manuscript(path)
    assert book.metadata.title == "Salt"
    assert book.metadata.author == "A. Rivers"
    assert "title:" not in " ".join(b.text for b in book.all_blocks() if hasattr(b, "text"))


def test_a_utf16_manuscript_loads_with_its_real_structure(tmp_path):
    path = tmp_path / "book.txt"
    path.write_bytes(
        "# One\n\nText.\n\n# Two\n\nMore text.\n".encode("utf-16"))
    book = load_manuscript(path)
    assert [c.title for c in book.chapters] == ["One", "Two"]


# --- front matter --------------------------------------------------------
def test_front_matter_is_metadata_and_never_body_text():
    """Left in, its fences parse as scene breaks and its fields as prose.

    The book opened with a thematic break and the line "title: The Salt Road
    author: A. Rivers" set as a paragraph.
    """
    book = parse_markdown(
        "---\ntitle: The Salt Road\nauthor: A. Rivers\n---\n\n# One\n\nText.\n")
    assert book.orphan_blocks == []
    assert book.chapters[0].preamble == [Paragraph("Text.")]


def test_a_title_in_front_matter_survives_structure_inference(tmp_path):
    """Two of this pipeline's own features colliding.

    A manuscript with no ATX headings is re-parsed from inferred ones, and the
    re-parse produced a fresh Book - discarding the title read from the front
    matter. The author was told "this manuscript does not say what it is
    called" by a file that says so on its first line.
    """
    path = tmp_path / "book.txt"
    path.write_text(
        "---\ntitle: The Salt Road\nauthor: A. Rivers\n---\n\n"
        "One\n===\n\nText.\n\nTwo\n===\n\nMore text.\n",
        encoding="utf-8",
    )
    notes = []
    book = load_manuscript(path, on_note=notes.append)

    assert any("inferred" in note.lower() for note in notes)
    assert [c.title for c in book.chapters] == ["One", "Two"]
    assert book.metadata.title == "The Salt Road"
    assert book.metadata.author == "A. Rivers"


# --- verse, and the things that look like it -----------------------------
def test_a_cast_list_with_one_long_entry_keeps_its_line_breaks():
    """Hamlet's dramatis personae came out as a prose slab.

    The rule was a single line-length threshold, and the longest cast line -
    "HAMLET, Prince of Denmark, son of the late King Hamlet and Queen
    Gertrude" - is 73 characters. One entry in the Folger text runs to 119.
    A list with a long entry is still a list.
    """
    from kdp.ingest import _line_breaks_are_meaningful
    assert _line_breaks_are_meaningful([
        "THE GHOST",
        "HAMLET, Prince of Denmark, son of the late King Hamlet and Queen Gertrude",
        "QUEEN GERTRUDE, widow of King Hamlet, now married to Claudius",
        "KING CLAUDIUS, brother to the late King Hamlet",
        "OPHELIA",
        "LAERTES, her brother",
    ])


def test_a_list_whose_longest_entry_comes_last_is_still_a_list():
    """The short-last-line allowance must not be granted to a long last line."""
    from kdp.ingest import _line_breaks_are_meaningful
    assert _line_breaks_are_meaningful([
        "THE WATCHMAN, keeper of the north gate",
        "ISOLDE, a traveller arriving after dark",
        "THE MAGISTRATE, who has not slept in three days",
        "A CHORUS OF TOWNSPEOPLE, who speak as one and are never named",
    ])


def test_prose_wrapped_at_a_wide_column_is_still_prose():
    """Every line but the last ends at the same margin. That is a paragraph."""
    from kdp.ingest import _line_breaks_are_meaningful
    assert not _line_breaks_are_meaningful([
        "The sun had not yet risen over the long grey wall of the harbour, and",
        "the boats were still tied up against the quay, their masts moving in",
        "a slow unison that nobody on the shore was awake enough to notice at",
        "that hour of the morning.",
    ])


def test_a_long_line_among_long_lines_is_prose():
    """The typical line decides it, not the longest one."""
    from kdp.ingest import _line_breaks_are_meaningful
    assert not _line_breaks_are_meaningful([
        "Something quite long that runs well past the short-line threshold here,",
        "And something else quite long that also runs past the threshold again,",
        "And a third line of the same generous width to settle the question.",
    ])
