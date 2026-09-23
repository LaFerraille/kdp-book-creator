"""Rendering tests.

The LaTeX-generation tests are fast and always run. The tests that actually
invoke XeLaTeX skip when no engine is installed, so the suite stays useful on
a machine without TeX.
"""
import hashlib

import pytest
from conftest import HAS_ENGINE

from kdp import fonts
from kdp.bookspec import BookSpec
from kdp.ingest import parse_markdown
from kdp.ir import Metadata
from kdp.render_print import build_latex, render_interior

needs_engine = pytest.mark.skipif(not HAS_ENGINE, reason="no LaTeX engine installed")


@pytest.fixture(autouse=True)
def _every_font_installed(request, monkeypatch):
    """Source generation tests the LaTeX we write, not this machine's fonts.

    The rendering class below needs the real fonts, so it is left alone.
    """
    if request.cls is None:
        monkeypatch.setattr(fonts, "_package_exists", lambda package: True)


SAMPLE = """# Chapitre 1 — La boutique
### Automne

## I. L'enseigne

Comme premier jour, « on verra bien » — *brouillé*, 200 $ et 100 % sûr.

## II. Suite

Du texte.

# Chapitre 2 — Le papier

## I. La cuve

Encore du texte.
"""


def _book():
    return parse_markdown(SAMPLE, Metadata(title="Été", author="J", language="fr"))


# --- source generation ---------------------------------------------------
def test_page_size_matches_the_trim_when_there_is_no_bleed():
    tex = build_latex(_book(), BookSpec(trim_w=6.0, trim_h=9.0), 200)
    assert r"\setstocksize{9.0000in}{6.0000in}" in tex


def test_bleed_enlarges_the_stock_but_not_the_trim():
    tex = build_latex(_book(), BookSpec(trim_w=6.0, trim_h=9.0, bleed=True), 200)
    assert r"\setstocksize{9.2500in}{6.1250in}" in tex
    assert r"\settrimmedsize{9.0000in}{6.0000in}{*}" in tex


def test_language_selects_the_polyglossia_profile():
    tex = build_latex(_book(), BookSpec(language="fr"), 200)
    assert r"\setmainlanguage{french}" in tex


def test_unknown_language_falls_back_to_english():
    tex = build_latex(_book(), BookSpec(language="xx"), 200)
    assert r"\setmainlanguage{english}" in tex


def test_chapter_subtitle_is_not_a_heading():
    """It must not reach the table of contents or the running heads."""
    tex = build_latex(_book(), BookSpec(), 200)
    assert r"\chaptersubtitle{Automne}" in tex
    assert r"\section{Automne}" not in tex


def test_specials_are_escaped_in_the_body():
    tex = build_latex(_book(), BookSpec(), 200)
    assert r"200 \$" in tex and r"100 \%" in tex


def test_hyperref_is_not_loaded():
    """It would add bookmarks and annotations, which KDP rejects."""
    assert "hyperref" not in build_latex(_book(), BookSpec(), 200)


def test_gutter_follows_the_assumed_page_count():
    thin = build_latex(_book(), BookSpec(), 100)
    thick = build_latex(_book(), BookSpec(), 600)
    assert thin != thick, "a thicker book must be typeset with a wider gutter"


# --- real rendering ------------------------------------------------------
@needs_engine
class TestRendering:
    def test_renders_a_pdf_at_the_right_page_size(self, tmp_path):
        pikepdf = pytest.importorskip("pikepdf")
        spec = BookSpec(trim_w=6.0, trim_h=9.0, paper="cream",
                        language="fr", font="Palatino")
        pdf, pages, passes, _ = render_interior(_book(), spec, tmp_path)
        assert pages > 0 and passes >= 1
        with pikepdf.open(pdf) as doc:
            box = [float(v) for v in doc.pages[0].MediaBox]
            assert box[2] == pytest.approx(432.0)   # 6in
            assert box[3] == pytest.approx(648.0)   # 9in

    def test_records_the_page_count_on_the_spec(self, tmp_path):
        spec = BookSpec(font="Palatino", language="fr")
        _, pages, _, _ = render_interior(_book(), spec, tmp_path)
        assert spec.page_count == pages

    def test_strips_document_metadata(self, tmp_path):
        pikepdf = pytest.importorskip("pikepdf")
        pdf, _, _, _ = render_interior(_book(), BookSpec(font="Palatino"), tmp_path)
        with pikepdf.open(pdf) as doc:
            assert not dict(doc.docinfo)

    def test_embeds_every_font(self, tmp_path):
        """KDP rejects unembedded fonts, and the failure is invisible locally."""
        pikepdf = pytest.importorskip("pikepdf")
        pdf, _, _, _ = render_interior(_book(), BookSpec(font="Palatino"), tmp_path)
        with pikepdf.open(pdf) as doc:
            for page in doc.pages:
                for font in (page.get("/Resources", {}).get("/Font", {}) or {}).values():
                    d = font.get("/FontDescriptor")
                    if d is None and font.get("/DescendantFonts"):
                        d = font["/DescendantFonts"][0].get("/FontDescriptor")
                    assert d is not None
                    assert any(k in d for k in ("/FontFile", "/FontFile2", "/FontFile3"))

    def test_build_is_reproducible(self, tmp_path):
        """Two builds of an unchanged manuscript must be byte-identical."""
        digests = []
        for name in ("a", "b"):
            out = tmp_path / name
            pdf, _, _, _ = render_interior(_book(), BookSpec(font="Palatino"), out)
            digests.append(hashlib.sha256(pdf.read_bytes()).hexdigest())
        assert digests[0] == digests[1]

    def test_missing_font_fails_with_an_actionable_message(self, tmp_path):
        """Never substitute silently: a different font changes the spine width."""
        from kdp.render_print import RenderError
        spec = BookSpec(font="NoSuchFontExistsAnywhere123")
        with pytest.raises(RenderError) as exc:
            render_interior(_book(), spec, tmp_path)
        assert "not installed" in str(exc.value).lower() or "font" in str(exc.value).lower()


# --- duplicate numbering -------------------------------------------------
def test_self_numbered_titles_suppress_latex_numbering():
    """Otherwise headings read "Chapitre 1. Chapitre 1 — La boutique"."""
    tex = build_latex(_book(), BookSpec(), 200)
    assert r"\renewcommand{\printchapternum}{}" in tex
    assert r"\setsecnumdepth{part}" in tex


def test_chaptermark_is_overridden_after_the_pagestyle_not_before():
    """memoir's headings style installs its own; an earlier override is lost."""
    tex = build_latex(_book(), BookSpec(running_heads=True), 200)
    assert tex.index(r"\pagestyle{headings}") < tex.index(r"\renewcommand{\chaptermark}")


def test_plain_titles_keep_normal_numbering():
    book = parse_markdown("# Beginnings\n\n## Opening\n\nx\n\n# Middles\n\n## Closing\n\ny\n")
    tex = build_latex(book, BookSpec(), 200)
    assert r"\renewcommand{\printchapternum}{}" not in tex
    assert r"\setsecnumdepth" not in tex


def test_foreign_italics_get_a_hyphenation_suppressing_wrapper():
    """French hyphenation applied to a Spanish word breaks it in the wrong place."""
    tex = build_latex(_book(), BookSpec(italic_role="foreign"), 200)
    assert r"\newcommand{\foreignphrase}" in tex
    assert r"\hyphenpenalty=10000" in tex
    assert r"\foreignphrase{brouillé}" in tex


def test_emphasis_italics_stay_plain_textit():
    tex = build_latex(_book(), BookSpec(italic_role="emphasis"), 200)
    assert r"\newcommand{\foreignphrase}" not in tex
    assert r"\textit{brouillé}" in tex
