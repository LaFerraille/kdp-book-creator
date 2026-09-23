"""Cover drawing tests.

The geometry itself is tested in test_geometry.py without rendering anything.
These cover what the drawing code does *inside* that geometry.
"""
import pytest
from conftest import HAS_ENGINE

from kdp import fonts
from kdp.cover import CoverError, barcode_zone, build_cover_latex, render_cover
from kdp.geometry import CoverGeometry
from kdp.ir import Metadata

needs_engine = pytest.mark.skipif(not HAS_ENGINE, reason="no LaTeX engine installed")


@pytest.fixture(autouse=True)
def _every_font_installed(request, monkeypatch):
    """Source generation tests the LaTeX we write, not this machine's fonts.

    The rendering class below needs the real fonts, so it is left alone.
    """
    if request.cls is None:
        monkeypatch.setattr(fonts, "_package_exists", lambda package: True)


META = Metadata(title="L'Atelier des Reliures", subtitle="Roman — Lyon", author="Jeanne Delorme")


def _geo(pages=350):
    return CoverGeometry.paperback(5.5, 8.5, pages, "cream")


# --- source generation ---------------------------------------------------
def test_page_size_equals_the_computed_cover_geometry():
    g = _geo()
    tex = build_cover_latex(g, META)
    assert "paperwidth=%.4fin" % g.width in tex
    assert "paperheight=%.4fin" % g.height in tex


def test_spine_text_appears_when_the_book_is_thick_enough():
    tex = build_cover_latex(_geo(350), META)
    assert "rotate=-90" in tex


def test_spine_text_is_omitted_below_kdp_threshold():
    """KDP rejects spine text under 79 pages."""
    tex = build_cover_latex(_geo(60), META)
    assert "rotate=-90" not in tex


def test_spine_text_can_be_suppressed_explicitly():
    assert "rotate=-90" not in build_cover_latex(_geo(350), META, spine_text=False)


def test_spine_separator_is_a_latex_command_not_literal_text():
    """Escaping the joined string printed a literal '\\quad' on the spine."""
    tex = build_cover_latex(_geo(350), META)
    assert r"\textbackslash{}quad" not in tex
    assert r"\quad" in tex


def test_title_is_escaped_but_accents_survive():
    tex = build_cover_latex(_geo(), Metadata(title="100 % Papier & Co", author="A"))
    assert r"100 \% Papier \& Co" in tex


def test_unknown_template_is_refused():
    with pytest.raises(CoverError):
        build_cover_latex(_geo(), META, template="hologram")


def test_background_image_is_placed_across_the_whole_cover():
    g = _geo()
    tex = build_cover_latex(g, META, background="art.png")
    assert "includegraphics[width=%.4fin,height=%.4fin]{art.png}" % (g.width, g.height) in tex


# --- barcode zone --------------------------------------------------------
def test_barcode_zone_sits_on_the_back_panel():
    g = _geo()
    x, y, w, h = barcode_zone(g)
    assert g.back_panel_x <= x
    assert x + w <= g.spine_x, "barcode must not reach the spine"
    assert y >= g.edge, "barcode must clear the bleed"
    assert (w, h) == (2.0, 1.2)


def test_barcode_zone_moves_with_the_trim_size():
    small = barcode_zone(CoverGeometry.paperback(5.0, 8.0, 200, "white"))
    large = barcode_zone(CoverGeometry.paperback(8.5, 11.0, 200, "white"))
    assert large[0] > small[0]


# --- real rendering ------------------------------------------------------
@needs_engine
class TestCoverRendering:
    def test_renders_one_page_at_the_exact_geometry(self, tmp_path):
        pikepdf = pytest.importorskip("pikepdf")
        g = _geo()
        pdf = render_cover(g, META, tmp_path, template="plain", blurb="Un résumé.")
        with pikepdf.open(pdf) as doc:
            assert len(doc.pages) == 1
            box = [float(v) for v in doc.pages[0].MediaBox]
            assert (box[2] - box[0]) / 72 == pytest.approx(g.width, abs=0.01)
            assert (box[3] - box[1]) / 72 == pytest.approx(g.height, abs=0.01)

    def test_cover_passes_preflight(self, tmp_path):
        from kdp.preflight import preflight_cover
        g = _geo()
        pdf = render_cover(g, META, tmp_path, blurb="Un résumé.")
        report = preflight_cover(pdf, g)
        assert report.errors == [], report.summary()

    def test_cover_is_not_blank(self, tmp_path):
        """TikZ's `current page` needs a second pass; one pass draws nothing."""
        from kdp.preflight import _page_content
        pikepdf = pytest.importorskip("pikepdf")
        pdf = render_cover(_geo(), META, tmp_path, blurb="Un résumé assez long.")
        with pikepdf.open(pdf) as doc:
            content = _page_content(doc.pages[0])
        assert len(content) > 2000, "cover content stream is suspiciously small"


def test_the_cover_carries_no_ornament():
    """Decoration on a cover is what a layout looks like when it isn't solved.

    A gold rule across an empty middle third reads as AI slop, and it was: it
    existed to fill space the type should have occupied.
    """
    g = CoverGeometry.paperback(5.5, 8.5, 250, "cream")
    tex = build_cover_latex(g, META)
    assert r"\draw" not in tex          # no rules
    assert r"\fill[accent" not in tex   # no colour bands
    assert "accent" not in tex


def test_only_one_cover_template_exists():
    from kdp.cover import TEMPLATES
    assert TEMPLATES == ("plain",)
