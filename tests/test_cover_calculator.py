"""Cover-calculator verification.

The parsing is pure and always tested. Actually driving KDP's live page is
marked `network` and excluded by default: a test suite that fails when Amazon
is slow, or when you are on a train, is a test suite people learn to ignore.
Run it deliberately with `-m network`.
"""
import pytest

from kdp.cover_calculator import (
    CalculatorResult,
    CalculatorUnavailable,
    parse_results,
    verify,
)
from kdp.geometry import CoverGeometry

# The table exactly as the live page rendered it for a 350-page 5.5x8.5 cream
# paperback, captured so the parser is tested against reality, not a guess.
LIVE_SAMPLE = """
Calculate dimensions
Download Template
#	Description	Width (in)	Height (in)
1	Full Cover 	12.125	8.75
2	Front Cover 	5.5	8.5
3	Safe Area 	5.375	8.25
4	Bleed 	0.125	0.125
5	Margin 	0.125	0.125
#	Description	Width (in)	Height (in)
6	Spine 	0.875	8.5
7	Spine Safe Area 	0.75	8.25
8	Spine Margin 	0.062	0.062
9	Barcode Margin 	0.25	0.25
Image for reference only
"""


def test_parses_every_row_of_the_live_table():
    r = parse_results(LIVE_SAMPLE)
    assert r.full_cover == (12.125, 8.75)
    assert r.front_cover == (5.5, 8.5)
    assert r.spine == (0.875, 8.5)
    assert r.safe_area == (5.375, 8.25)
    assert r.spine_margin == (0.062, 0.062)
    assert r.barcode_margin == (0.25, 0.25)


def test_ignores_surrounding_page_furniture():
    assert "calculate dimensions" not in parse_results(LIVE_SAMPLE).raw_rows


def test_our_geometry_agrees_with_the_captured_live_response():
    """The regression alarm: this failing means KDP changed a specification."""
    g = CoverGeometry.paperback(5.5, 8.5, 350, "cream")
    assert parse_results(LIVE_SAMPLE).compare(g) == []


def test_compare_reports_a_real_disagreement():
    """The check must be able to fail, or it guarantees nothing."""
    g = CoverGeometry.paperback(6.0, 9.0, 350, "cream")   # different trim
    problems = parse_results(LIVE_SAMPLE).compare(g)
    assert problems and any("full cover width" in p for p in problems)


def test_missing_values_are_reported_not_silently_passed():
    problems = CalculatorResult().compare(CoverGeometry.paperback(5.5, 8.5, 350, "cream"))
    assert len(problems) == 3


def test_empty_text_yields_no_rows():
    assert parse_results("nothing useful here").raw_rows == {}


@pytest.mark.network
def test_live_calculator_matches_our_arithmetic():
    """Drives the real page. Excluded by default; run with `-m network`."""
    g = CoverGeometry.paperback(5.5, 8.5, 350, "cream")
    try:
        result, problems = verify(g, "cream")
    except CalculatorUnavailable as exc:
        pytest.skip(str(exc))
    assert problems == [], f"KDP and our geometry disagree: {problems}"
    assert result.full_cover == (12.125, 8.75)
