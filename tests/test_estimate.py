"""The estimator only has to be close enough to make trim size a real choice."""
import pytest

from kdp.estimate import compare_trim_sizes, estimate_pages


def test_estimate_is_in_a_plausible_range_for_the_example_manuscript():
    """101k French words at 6x9/11pt should land in the low-to-mid 300s.

    A trade paperback of this length runs 320-380 pages; anything outside that
    means the model is broken, not merely imprecise.
    """
    est = estimate_pages(100_732, 6.0, 9.0, font_pt=11, language="fr", chapters=15)
    assert 300 <= est.pages <= 400
    assert 250 <= est.words_per_page <= 400


def test_smaller_trim_yields_more_pages():
    big = estimate_pages(100_000, 6.0, 9.0, chapters=15)
    small = estimate_pages(100_000, 5.0, 8.0, chapters=15)
    assert small.pages > big.pages


def test_larger_font_yields_more_pages():
    small_type = estimate_pages(100_000, 6.0, 9.0, font_pt=10)
    large_type = estimate_pages(100_000, 6.0, 9.0, font_pt=14)
    assert large_type.pages > small_type.pages


def test_chapters_add_pages():
    without = estimate_pages(50_000, 6.0, 9.0, chapters=0)
    with_many = estimate_pages(50_000, 6.0, 9.0, chapters=30)
    assert with_many.pages > without.pages


def test_compare_trim_sizes_covers_each_candidate():
    result = compare_trim_sizes(80_000, [(5.5, 8.5), (6.0, 9.0)], chapters=12)
    assert set(result) == {(5.5, 8.5), (6.0, 9.0)}
    assert result[(5.5, 8.5)].pages > result[(6.0, 9.0)].pages


def test_impossible_margins_are_rejected_not_silently_wrong():
    with pytest.raises(ValueError):
        estimate_pages(10_000, 1.0, 1.0)
