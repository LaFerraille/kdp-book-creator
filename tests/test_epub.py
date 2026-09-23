"""EPUB structure tests.

An EPUB is a zip with rules that readers enforce strictly - mimetype first and
uncompressed, every manifest entry present, every document well-formed XML.
check_epub() covers what epubcheck would catch that we can catch without it.
"""
import zipfile

import pytest

from kdp.ingest import parse_markdown
from kdp.ir import Metadata
from kdp.render_epub import check_epub, inline_to_html, render_epub

SAMPLE = """# Chapitre 1 — La boutique
### Automne

## I. L'enseigne

Un mot *brouillé* et **du gras**, 100 % sûr & certain.

## II. Suite

> Une citation.

# Chapitre 2 — Le papier

## I. La cuve

Du texte avec [un lien](https://example.com).
"""


def _book():
    return parse_markdown(SAMPLE, Metadata(title="Été", author="J", language="fr"))


@pytest.fixture
def epub(tmp_path):
    return render_epub(_book(), tmp_path / "book.epub")


# --- inline conversion ---------------------------------------------------
def test_escapes_xml_specials():
    assert inline_to_html("a & b < c") == "a &amp; b &lt; c"


def test_bold_and_italic():
    assert inline_to_html("*a* and **b**") == "<em>a</em> and <strong>b</strong>"


def test_foreign_italics_use_i_not_em():
    """<em> means stress; a screen reader may pronounce it. A Spanish noun is
    not stressed, it is foreign."""
    assert inline_to_html("*croquetas*", foreign_italics=True) == '<i class="foreign">croquetas</i>'


def test_links_stay_live_unlike_the_print_path():
    out = inline_to_html("see [docs](https://x.com/a&b)")
    assert '<a href="https://x.com/a&amp;b">docs</a>' in out


def test_accents_survive():
    assert "Été brûlé" in inline_to_html("Été brûlé")


# --- archive structure ---------------------------------------------------
def test_epub_passes_structural_checks(epub):
    assert check_epub(epub) == []


def test_mimetype_is_first_and_uncompressed(epub):
    with zipfile.ZipFile(epub) as z:
        assert z.namelist()[0] == "mimetype"
        assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED


def test_one_document_per_chapter(epub):
    with zipfile.ZipFile(epub) as z:
        chapters = [n for n in z.namelist() if n.startswith("OEBPS/chapter-")]
    assert len(chapters) == 2


def test_language_is_declared(epub):
    with zipfile.ZipFile(epub) as z:
        assert "<dc:language>fr</dc:language>" in z.read("OEBPS/content.opf").decode()


def test_navigation_lists_every_chapter(epub):
    with zipfile.ZipFile(epub) as z:
        nav = z.read("OEBPS/nav.xhtml").decode()
    assert "Chapitre 1" in nav and "Chapitre 2" in nav


def test_chapter_subtitle_is_not_a_heading(epub):
    """It must not appear in the navigation as a section."""
    with zipfile.ZipFile(epub) as z:
        doc = z.read("OEBPS/chapter-001.xhtml").decode()
        nav = z.read("OEBPS/nav.xhtml").decode()
    assert '<p class="subtitle">Automne</p>' in doc
    assert "Automne" not in nav


def test_every_document_is_well_formed_xml(epub):
    from xml.etree import ElementTree
    with zipfile.ZipFile(epub) as z:
        for name in z.namelist():
            if name.endswith(".xhtml"):
                ElementTree.fromstring(z.read(name))


# --- the checker must be able to fail ------------------------------------
def test_check_detects_a_compressed_mimetype(tmp_path):
    bad = tmp_path / "bad.epub"
    with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")   # compressed
        z.writestr("META-INF/container.xml", "<x/>")
    problems = check_epub(bad)
    assert any("uncompressed" in p for p in problems)


def test_check_detects_a_manifest_entry_that_is_not_in_the_archive(tmp_path):
    bad = tmp_path / "bad.epub"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", "<x/>")
        z.writestr("OEBPS/content.opf",
                   '<package><manifest><item href="ghost.xhtml"/></manifest>'
                   "<dc:language>en</dc:language></package>")
        z.writestr("OEBPS/nav.xhtml", "<html/>")
    assert any("ghost.xhtml" in p for p in check_epub(bad))


def test_check_detects_malformed_xhtml(tmp_path):
    bad = tmp_path / "bad.epub"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", "<x/>")
        z.writestr("OEBPS/content.opf", "<package><dc:language>en</dc:language></package>")
        z.writestr("OEBPS/nav.xhtml", "<html><p>unclosed</html>")
    assert any("well-formed" in p for p in check_epub(bad))


def test_two_builds_of_the_same_book_are_byte_identical(tmp_path):
    """The print path takes trouble to be reproducible; the EPUB quietly was not.

    zipfile stamps the current local time into every entry, so two builds of an
    unchanged manuscript differed - and a build in another timezone differed
    again - which makes any diff in the output meaningless as a signal.
    """
    book = parse_markdown("# One\n\nText.\n\n# Two\n\nMore text.\n",
                          Metadata(title="Reproducible", language="en"))
    first = render_epub(book, tmp_path / "a.epub")
    second = render_epub(book, tmp_path / "b.epub")
    assert first.read_bytes() == second.read_bytes()
