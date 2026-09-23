"""Reading Word without pandoc: what survives the crossing into Markdown.

DOCX is the format most authors actually hand you, and it is the one input
whose content cannot be read in a diff. Every defect found here was found by
opening a rendered PDF and seeing asterisks or backslashes on the page, which
is the most expensive way there is to find a parser bug.
"""
import pytest
from conftest import make_docx

from kdp import docx
from kdp.latex import inline_to_latex


def markdown_of(tmp_path, source, **metadata):
    path = make_docx.write_docx(tmp_path / "book.docx", source, **metadata)
    return docx.to_markdown(path)


# --- emphasis ------------------------------------------------------------
def test_a_run_that_is_both_bold_and_italic_prints_as_neither_marker(tmp_path):
    """Word's commonest double emphasis used to print its own asterisks.

    A run with <w:b/> and <w:i/> converts to ***text***, which the shared
    inline tokenizer could not parse - it read `**text**` and left a bare pair
    of asterisks either side. The book then carried "*Tannhauser*" with the
    marks visible, in print, on paper.
    """
    md = markdown_of(tmp_path, "# One\n\nHe read ***Tannhauser*** twice.\n")
    assert "***Tannhauser***" in md
    assert inline_to_latex(md.split("He read ")[1].split(" twice")[0]) \
        == r"\textbf{\textit{Tannhauser}}"


def test_bold_and_italic_alone_each_survive(tmp_path):
    md = markdown_of(tmp_path, "# One\n\nA **strong** and an *aside*.\n")
    assert "**strong**" in md and "*aside*" in md


def test_the_space_around_an_emphasised_run_is_lifted_out_of_it(tmp_path):
    """Markdown ignores a marker that does not hug its word."""
    md = markdown_of(tmp_path, "# One\n\nthe **word** after\n")
    assert "the **word** after" in md


# --- headings ------------------------------------------------------------
def test_heading_levels_become_atx_headings(tmp_path):
    md = markdown_of(tmp_path, "# Chapter\n\n## Section\n\nText.\n")
    assert "# Chapter" in md
    assert "## Section" in md


@pytest.mark.parametrize("style,level", [
    ("Heading1", 1), ("heading 1", 1), ("Überschrift1", 1),
    ("Titre2", 2), ("Titolo3", 3), ("Título2", 2),
])
def test_word_heading_styles_are_recognised_in_every_locale(style, level):
    """Localised templates spell the style name in their own language."""
    assert docx._heading_level(style) == level


@pytest.mark.parametrize("style", ["Normal", "BodyText", "", None, "Heading"])
def test_a_body_style_is_not_a_heading(style):
    assert docx._heading_level(style) is None


# --- escaping ------------------------------------------------------------
def test_brackets_and_backticks_from_prose_are_escaped(tmp_path):
    """A bracket typed in Word is a bracket, not the start of a link."""
    md = markdown_of(tmp_path, "# One\n\nHe said [sic] and `then` left.\n")
    assert r"\[sic\]" in md and r"\`then\`" in md


def test_emphasis_markers_already_in_the_text_are_left_alone(tmp_path):
    """A .docx exported from Markdown by a tool that did not map emphasis.

    Escaping them and never unescaping printed "\\**3 000 pages**" on the page.
    Every such file in practice means the emphasis.
    """
    md = markdown_of(tmp_path, "# One\n\nElle a relie **3 000 pages** cette annee.\n")
    assert "\\" not in md
    assert "**3 000 pages**" in md


# --- metadata ------------------------------------------------------------
def test_the_title_comes_from_the_document_properties(tmp_path):
    path = make_docx.write_docx(tmp_path / "b.docx", "# One\n\nText.\n",
                                title="The Salt Road", author="A. Rivers")
    assert docx.metadata_from(path) == {"title": "The Salt Road",
                                        "author": "A. Rivers"}


@pytest.mark.parametrize("placeholder", ["Un-named", "Untitled", "Normal.dotm",
                                         "Document", "Microsoft Word"])
def test_words_own_placeholders_are_not_a_title(tmp_path, placeholder):
    """Word writes these when nobody filled the field in."""
    path = make_docx.write_docx(tmp_path / "b.docx", "# One\n\nText.\n",
                                title=placeholder)
    assert "title" not in docx.metadata_from(path)


def test_a_file_without_properties_yields_nothing(tmp_path):
    path = make_docx.write_docx(tmp_path / "b.docx", "# One\n\nText.\n")
    assert docx.metadata_from(path) == {}


# --- refusals ------------------------------------------------------------
def test_a_renamed_doc_is_named_as_such(tmp_path):
    path = tmp_path / "old.docx"
    path.write_bytes(b"not a zip at all")
    with pytest.raises(docx.DocxError) as caught:
        docx.to_markdown(path)
    assert "save it as .docx" in str(caught.value)


def test_a_zip_that_is_not_a_word_document_says_which_part_is_missing(tmp_path):
    import zipfile
    path = tmp_path / "archive.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("hello.txt", "not a document")
    with pytest.raises(docx.DocxError) as caught:
        docx.to_markdown(path)
    assert "word/document.xml" in str(caught.value)
