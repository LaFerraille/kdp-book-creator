"""Estimate a page count before typesetting anything.

The interview needs this to make trim size a real choice: "6x9 gives about 338
pages, 5.5x8.5 about 390 and a thicker spine" is a decision someone can make,
where "which trim size?" is not.

This is a model, not a measurement. It exists to be shown *before* a render
costs anything. The authoritative count always comes from the rendered PDF, and
render_print.py uses that to settle the margin fixed point. Treat every number
here as approximate and label it that way in the interface.
"""
from dataclasses import dataclass

from . import languages, specs
from .geometry import design_margins


def _MIN_PAGES():
    """KDP's shortest printable book, from the margin table rather than a literal."""
    return specs.margins()[0]["min_pages"]


def _MAX_PAGES():
    return specs.margins()[-1]["max_pages"]

PT_PER_INCH = 72.0

# Average glyph advance as a fraction of font size, for a typical serif text
# face. Garamond and Palatino sit near 0.46; Times is a little wider.
AVG_CHAR_WIDTH_RATIO = 0.48

# Typesetting never fills a measure perfectly: line breaking, paragraph last
# lines and indents lose some. Calibrated against rendered output.
LINE_FILL_EFFICIENCY = 0.92


@dataclass(frozen=True)
class PageEstimate:
    pages: int
    words_per_page: int
    lines_per_page: int

    def __str__(self):
        return f"about {self.pages} pages"


def estimate_pages(
    words,
    trim_w,
    trim_h,
    font_pt=11.0,
    leading_pt=None,
    language="en",
    chapters=0,
    generosity=1.0,
    seed_pages=200,
):
    """Approximate page count for a body of text at a given trim and size.

    ``seed_pages`` breaks the circularity: the gutter depends on the page count,
    which is what we are trying to find. We take a first guess, then re-solve
    once with the resulting count, which is enough for an estimate. The renderer
    resolves it properly by iterating on real output.
    """
    leading_pt = leading_pt or font_pt * 1.32

    def solve(assumed_pages):
        assumed_pages = max(_MIN_PAGES(), min(assumed_pages, _MAX_PAGES()))
        margins = design_margins(assumed_pages, trim_w, trim_h, generosity=generosity)

        text_w_in = margins.text_width(trim_w)
        text_h_in = margins.text_height(trim_h)
        if text_w_in <= 0 or text_h_in <= 0:
            raise ValueError(
                f"margins leave no text area on a {trim_w}x{trim_h} page"
            )

        chars_per_line = (text_w_in * PT_PER_INCH) / (font_pt * AVG_CHAR_WIDTH_RATIO)
        chars_per_line *= LINE_FILL_EFFICIENCY
        lines = int((text_h_in * PT_PER_INCH) // leading_pt)

        cpw = languages.chars_per_word(language)
        words_page = max(1, int(chars_per_line * lines / cpw))

        body = -(-words // words_page)           # ceiling division
        # Each chapter opens on a fresh page, usually with a sunk title, and
        # roughly half end with a mostly blank verso.
        body += int(chapters * 1.5)
        return body, words_page, lines

    pages, words_page, lines = solve(seed_pages)
    pages, words_page, lines = solve(pages)      # re-solve with a better guess
    return PageEstimate(pages=pages, words_per_page=words_page, lines_per_page=lines)


def compare_trim_sizes(words, candidates, **kw):
    """Page counts across several trim sizes, for presenting a real choice."""
    return {
        (w, h): estimate_pages(words, w, h, **kw)
        for w, h in candidates
    }
