"""Geometry is where KDP correctness lives, so it is tested against KDP's own
published numbers rather than against our expectations of them."""
import pytest

from kdp import specs
from kdp.geometry import (
    CoverGeometry,
    InteriorGeometry,
    design_margins,
    gutter_for_page_count,
    interior_page_size,
    outside_margin_for,
    spine_width,
)


# --- bleed ---------------------------------------------------------------
def test_bleed_matches_every_kdp_worked_example():
    """KDP publishes 29 trim -> page-size-with-bleed pairs. All must agree.

    This pins the asymmetry that is easy to get wrong: bleed widens a page by
    0.125" (outside edge only) but heightens it by 0.25" (top and bottom).
    """
    examples = specs.bleed_examples()
    assert len(examples) >= 25, "expected KDP's worked examples to be present"
    for ex in examples:
        tw, th = ex["trim"]
        want_w, want_h = ex["with_bleed"]
        got = interior_page_size(tw, th, bleed=True)
        assert got.width == pytest.approx(want_w, abs=0.006), f"{tw}x{th} width"
        assert got.height == pytest.approx(want_h, abs=0.006), f"{tw}x{th} height"


def test_no_bleed_page_equals_trim():
    assert interior_page_size(6.0, 9.0, bleed=False) == InteriorGeometry(6.0, 9.0)


# --- gutter brackets -----------------------------------------------------
@pytest.mark.parametrize("pages,gutter", [
    (24, 0.375), (150, 0.375),
    (151, 0.5), (300, 0.5),
    (301, 0.625), (500, 0.625),
    (501, 0.75), (700, 0.75),
    (701, 0.875), (828, 0.875),
])
def test_gutter_brackets_including_both_boundaries(pages, gutter):
    """Every bracket edge, because an off-by-one here silently ruins a book."""
    assert gutter_for_page_count(pages) == gutter


def test_gutter_rejects_page_counts_outside_kdp_range():
    with pytest.raises(ValueError):
        gutter_for_page_count(23)
    with pytest.raises(ValueError):
        gutter_for_page_count(829)


# --- spine ---------------------------------------------------------------
@pytest.mark.parametrize("paper,factor", [
    ("white", 0.002252), ("cream", 0.0025), ("groundwood", 0.00235),
    ("premium_color", 0.002347), ("standard_color", 0.002252),
])
def test_spine_width_uses_the_documented_factor(paper, factor):
    assert spine_width(300, paper) == pytest.approx(300 * factor)


def test_spine_width_rejects_unknown_paper():
    with pytest.raises(KeyError):
        spine_width(300, "papyrus")


# --- paperback cover -----------------------------------------------------
def test_paperback_cover_matches_kdp_formula():
    """Cover Width = Bleed + Back + Spine + Front + Bleed; Height = Bleed + Trim + Bleed.

    Worked by hand from topics/create-a-paperback-cover.md for a 6x9, 338-page
    cream paperback (the example manuscript):
      spine  = 338 * 0.0025            = 0.845
      width  = 0.125 + 6 + 0.845 + 6 + 0.125 = 13.095
      height = 0.125 + 9 + 0.125       = 9.25
    """
    cover = CoverGeometry.paperback(trim_w=6.0, trim_h=9.0, pages=338, paper="cream")
    assert cover.spine == pytest.approx(0.845)
    assert cover.width == pytest.approx(13.095)
    assert cover.height == pytest.approx(9.25)
    assert cover.allows_spine_text is True


def test_spine_text_not_allowed_under_79_pages():
    thin = CoverGeometry.paperback(trim_w=5.0, trim_h=8.0, pages=78, paper="white")
    assert thin.allows_spine_text is False
    at_threshold = CoverGeometry.paperback(trim_w=5.0, trim_h=8.0, pages=79, paper="white")
    assert at_threshold.allows_spine_text is True


def test_front_cover_panel_sits_right_of_the_spine():
    """The front panel's x-offset must clear bleed + back panel + spine."""
    c = CoverGeometry.paperback(trim_w=6.0, trim_h=9.0, pages=200, paper="white")
    assert c.front_panel_x == pytest.approx(0.125 + 6.0 + c.spine)
    assert c.back_panel_x == pytest.approx(0.125)
    assert c.spine_x == pytest.approx(0.125 + 6.0)


# --- hardcover cover -----------------------------------------------------
def test_hardcover_uses_wrap_not_bleed():
    """Hardcover wraps 0.51" around the case board instead of bleeding 0.125"."""
    c = CoverGeometry.hardcover(trim_w=6.0, trim_h=9.0, pages=300, paper="white")
    assert c.wrap == pytest.approx(0.51)
    assert c.height == pytest.approx(0.51 + 9.0 + 0.51)
    assert c.width == pytest.approx(0.51 + 6.0 + c.spine + 6.0 + 0.51)


def test_hardcover_headband_threshold():
    assert CoverGeometry.hardcover(6.0, 9.0, 120, "white").has_headband is False
    assert CoverGeometry.hardcover(6.0, 9.0, 121, "white").has_headband is True


# --- design margins ------------------------------------------------------
def test_design_margins_never_fall_below_kdp_minimums():
    """KDP publishes floors. Design values may exceed them, never undercut them."""
    for pages in (24, 150, 151, 300, 301, 500, 501, 700, 701, 828):
        for bleed in (False, True):
            m = design_margins(pages, 6.0, 9.0, bleed=bleed)
            assert m.inside >= gutter_for_page_count(pages)
            assert m.outside >= outside_margin_for(pages, bleed=bleed)


def test_design_margins_are_roomier_than_the_bare_minimum():
    """A book set at KDP's 0.25" floor looks cramped; we should not ship that."""
    m = design_margins(300, 6.0, 9.0)
    assert m.outside > outside_margin_for(300)
    assert m.top > 0 and m.bottom > 0


def test_gutter_exceeds_outside_margin_to_absorb_binding_creep():
    m = design_margins(400, 6.0, 9.0)
    assert m.inside > m.outside


def test_generosity_trades_pages_for_air():
    tight = design_margins(300, 6.0, 9.0, generosity=0.8)
    airy = design_margins(300, 6.0, 9.0, generosity=1.4)
    assert airy.text_width(6.0) < tight.text_width(6.0)


def test_text_area_is_positive_for_every_offered_trim_size():
    """Guards the smallest trim sizes, where fixed margins could eat the page."""
    from kdp import specs
    for t in specs.trim_sizes("paperback", "com"):
        m = design_margins(300, t["width"], t["height"])
        assert m.text_width(t["width"]) > 2.0, f'{t["width"]}x{t["height"]} too narrow'
        assert m.text_height(t["height"]) > 3.0
