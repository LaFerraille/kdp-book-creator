"""Page and cover geometry, derived strictly from KDP's published formulas.

Pure functions over numbers: no file I/O, no rendering, no network. Everything
KDP can reject a book for dimensionally is decided here, which is why this
module is the most heavily tested part of the project.

All measurements are in inches.
"""
from dataclasses import dataclass

from . import specs


@dataclass(frozen=True)
class InteriorGeometry:
    """The physical page size to typeset on."""
    width: float
    height: float


def interior_page_size(trim_w, trim_h, bleed=False):
    """Page size to typeset, given a trim size and whether the book bleeds.

    The asymmetry matters and is easy to get wrong: printing trims 0.125" from
    the top, bottom and outside edge, but not from the gutter. A bleed page is
    therefore one bleed wider and *two* bleeds taller. KDP's own table of worked
    examples confirms this for all 29 trim sizes it lists.
    """
    if not bleed:
        return InteriorGeometry(trim_w, trim_h)
    c = specs.constants()["interior"]
    return InteriorGeometry(
        trim_w + c["bleed_added_to_width"],
        trim_h + c["bleed_added_to_height"],
    )


def gutter_for_page_count(pages, clamp=False):
    """Minimum inside (gutter) margin KDP requires for this page count.

    The requirement grows in brackets, from 0.375" for a thin book to 0.875" for
    the thickest. Because the page count itself depends on the margin, callers
    resolve this by iteration - see render_print.py.

    ``clamp`` takes the nearest bracket instead of refusing, for callers that
    need *a* layout for a manuscript KDP could not print as it stands - a
    28-page draft still has to render so its author can see it and add pages.
    Reporting that the length is unpublishable is validation's job, not the
    renderer's, and conflating the two means a short draft crashes the build.
    """
    brackets = specs.margins()
    for bracket in brackets:
        if bracket["min_pages"] <= pages <= bracket["max_pages"]:
            return bracket["gutter"]
    if clamp:
        return brackets[0]["gutter"] if pages < brackets[0]["min_pages"] else brackets[-1]["gutter"]
    raise ValueError(
        f"{pages} pages is outside KDP's printable range "
        f"({brackets[0]['min_pages']}-{brackets[-1]['max_pages']} pages)"
    )


def outside_margin_for(pages, bleed=False, clamp=False):
    """Minimum top/bottom/outside margin, which is stricter when the book bleeds."""
    key = "outside_with_bleed" if bleed else "outside_no_bleed"
    brackets = specs.margins()
    for bracket in brackets:
        if bracket["min_pages"] <= pages <= bracket["max_pages"]:
            return bracket[key]
    if clamp:
        return brackets[0][key] if pages < brackets[0]["min_pages"] else brackets[-1][key]
    raise ValueError(f"{pages} pages is outside KDP's printable range")


@dataclass(frozen=True)
class Margins:
    """The four margins a page is actually set with, in inches."""
    inside: float
    outside: float
    top: float
    bottom: float

    def text_width(self, trim_w):
        return trim_w - self.inside - self.outside

    def text_height(self, trim_h):
        return trim_h - self.top - self.bottom


def design_margins(pages, trim_w, trim_h, bleed=False, generosity=1.0):
    """Typographically sound margins that also satisfy KDP's minimums.

    KDP publishes *floors*, not recommendations: 0.25" on the outside edge stops
    text being trimmed off, but a book actually set that way looks cramped. Real
    trade books use roughly a tenth of the page width outside and a little more
    inside, and that is what this returns - clamped up to KDP's minimum whenever
    the two disagree, never down.

    ``generosity`` scales the airiness: below 1.0 tightens the block to save
    pages (and printing cost), above 1.0 opens it up.
    """
    kdp_gutter = gutter_for_page_count(pages, clamp=True)
    kdp_outside = outside_margin_for(pages, bleed=bleed, clamp=True)

    outside = max(kdp_outside, 0.5 * generosity)
    # The gutter must also swallow the binding creep that KDP's bracket encodes.
    inside = max(kdp_gutter, outside + 0.125)
    vertical = max(0.5, 0.75 * generosity)

    return Margins(inside=inside, outside=outside, top=vertical, bottom=vertical)


def spine_width(pages, paper):
    """Spine thickness for a page count on a given paper stock.

    Raises KeyError for an unknown stock rather than guessing a factor: a wrong
    spine silently produces a cover that KDP rejects or prints misaligned.
    """
    return pages * specs.spine_factor(paper)


@dataclass(frozen=True)
class CoverGeometry:
    """A full wrap cover: back panel, spine and front panel as one canvas.

    Coordinates are measured from the bottom-left of the cover file, so panel
    offsets can be handed straight to a drawing backend.
    """
    width: float
    height: float
    spine: float
    trim_w: float
    trim_h: float
    pages: int
    edge: float           # bleed (paperback) or wrap (hardcover)
    binding: str
    hinge: float = 0.0

    # -- constructors ----------------------------------------------------
    @classmethod
    def paperback(cls, trim_w, trim_h, pages, paper):
        """Cover Width = Bleed + Back + Spine + Front + Bleed.

        Cover Height = Bleed + Trim Height + Bleed.
        """
        bleed = specs.constants()["paperback_cover"]["bleed"]
        spine = spine_width(pages, paper)
        return cls(
            width=bleed + trim_w + spine + trim_w + bleed,
            height=bleed + trim_h + bleed,
            spine=spine,
            trim_w=trim_w, trim_h=trim_h, pages=pages,
            edge=bleed, binding="paperback",
        )

    @classmethod
    def hardcover(cls, trim_w, trim_h, pages, paper):
        """Hardcover wraps around the case board instead of bleeding.

        The wrap (0.51") is glued to the inside cover, and a 0.4" hinge either
        side of the spine must stay clear of text and the barcode.
        """
        hc = specs.constants()["hardcover_cover"]
        wrap, hinge = hc["wrap"], hc["hinge"]
        spine = spine_width(pages, paper)
        return cls(
            width=wrap + trim_w + spine + trim_w + wrap,
            height=wrap + trim_h + wrap,
            spine=spine,
            trim_w=trim_w, trim_h=trim_h, pages=pages,
            edge=wrap, binding="hardcover", hinge=hinge,
        )

    # -- panel positions -------------------------------------------------
    @property
    def wrap(self):
        """The hardcover wrap allowance. Zero for a paperback, which bleeds instead."""
        return self.edge if self.binding == "hardcover" else 0.0

    @property
    def bleed(self):
        """The paperback bleed allowance. Zero for a hardcover, which wraps instead."""
        return self.edge if self.binding == "paperback" else 0.0

    @property
    def back_panel_x(self):
        """Left edge of the back cover panel."""
        return self.edge

    @property
    def spine_x(self):
        """Left edge of the spine."""
        return self.edge + self.trim_w

    @property
    def front_panel_x(self):
        """Left edge of the front cover panel, past the back panel and spine."""
        return self.edge + self.trim_w + self.spine

    # -- rules -----------------------------------------------------------
    @property
    def allows_spine_text(self):
        """KDP rejects spine text on books thinner than its threshold."""
        return self.pages >= specs.constants()["paperback_cover"]["spine_text_min_pages"]

    @property
    def has_headband(self):
        """Hardcovers above the threshold are bound with a headband."""
        if self.binding != "hardcover":
            return False
        return self.pages > specs.constants()["hardcover_cover"]["headband_min_pages"]

    @property
    def barcode_zone(self):
        """The rectangle on the back cover that must stay clear, in inches.

        (x, y, width, height) from the cover's bottom-left, the same corner the
        panel offsets above are measured from.

        KDP prints a barcode here whether or not you supply one, so anything
        underneath is printed over. The figures are KDP's published hardcover
        ones - the only ones it documents - which are the safer choice for a
        paperback too. It lives here, with the rest of the arithmetic that
        decides whether a cover is rejectable, so that preflight can measure
        against it without importing the renderer that draws it.
        """
        c = specs.constants()["hardcover_cover"]
        width, height = c["barcode_width"], c["barcode_height"]
        return (self.back_panel_x + self.trim_w - c["barcode_min_from_hinge"] - width,
                self.edge + c["barcode_min_from_bottom"],
                width, height)

    def summary(self):
        """One line for the build report."""
        return (
            f'{self.binding} cover {self.width:.3f}" x {self.height:.3f}" '
            f'(spine {self.spine:.3f}" at {self.pages} pages)'
        )
