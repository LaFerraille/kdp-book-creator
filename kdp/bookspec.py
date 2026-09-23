"""The resolved design decisions for one book.

Everything the interview settles ends up here, and this is what gets written to
book.yaml so a rebuild needs no re-interrogation. Validation against KDP happens
at construction: it is far cheaper to refuse an impossible combination than to
typeset 340 pages and discover the trim size cannot hold them.
"""
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclasses_fields

from . import specs
from .geometry import design_margins

PAPERS = ("white", "cream", "groundwood", "standard_color", "premium_color")


class SpecError(ValueError):
    """An impossible or KDP-rejectable combination, caught before rendering."""


@dataclass
class BookSpec:
    trim_w: float = 6.0
    trim_h: float = 9.0
    binding: str = "paperback"
    paper: str = "cream"
    marketplace: str = "com"

    font: str = "EB Garamond"
    font_pt: float = 11.0
    leading_ratio: float = 1.32
    # None means "not decided yet", which is different from "English". The
    # pipeline fills it from the manuscript, so a French book set from a book
    # type does not get English hyphenation - which costs six pages on a
    # 300-page memoir and breaks words in the wrong places throughout.
    language: str | None = None

    bleed: bool = False
    generosity: float = 1.0

    # Whether the typesetter adds its own numbers. None means "decide from the
    # manuscript": titles that already read "Chapitre 7 - Le retour" must not be
    # numbered again. Set explicitly, the author's answer wins - which it could
    # not before, because the renderer re-derived this and ignored the spec.
    number_chapters: bool | None = None
    number_sections: bool | None = None

    toc: bool = False
    toc_depth: str = "chapters"        # "chapters" or "chapters+sections"
    running_heads: bool = True
    page_numbers: bool = True
    indent_paragraphs: bool = True
    # "emphasis" (plain italic) or "foreign" (italic, hyphenation suppressed:
    # French rules applied to a Spanish word break it in the wrong place)
    italic_role: str = "emphasis"
    chapters_start_recto: bool = True

    # Filled in once the interior has actually been rendered.
    page_count: int | None = None

    extra: dict = field(default_factory=dict)

    # -- derived ---------------------------------------------------------
    @property
    def leading_pt(self):
        return self.font_pt * self.leading_ratio

    def margins(self, pages):
        return design_margins(
            pages, self.trim_w, self.trim_h,
            bleed=self.bleed, generosity=self.generosity,
        )

    def trim_entry(self):
        """The KDP table row for this trim size, or None if it is not offered."""
        for entry in specs.trim_sizes(self.binding, self.marketplace):
            if (abs(entry["width"] - self.trim_w) < 0.005
                    and abs(entry["height"] - self.trim_h) < 0.005):
                return entry
        return None

    def page_limits(self):
        """(min, max) pages for this trim size on this paper stock."""
        entry = self.trim_entry()
        if entry is None:
            return None
        return entry["papers"].get(self.paper)

    # -- validation ------------------------------------------------------
    def validate(self, pages=None):
        """Every check that can be made before rendering. Returns a list of problems.

        Kept as a list rather than raising on the first fault so the interview
        can show someone everything that is wrong at once.
        """
        problems = []

        if self.paper not in PAPERS:
            problems.append(f"Unknown paper stock {self.paper!r}; expected one of {PAPERS}.")

        entry = self.trim_entry()
        if entry is None:
            offered = ", ".join(
                f'{t["width"]}x{t["height"]}'
                for t in specs.trim_sizes(self.binding, self.marketplace)
            )
            problems.append(
                f'{self.trim_w}" x {self.trim_h}" is not a KDP {self.binding} trim '
                f"size for {self.marketplace}. Available: {offered}"
            )
        else:
            limits = entry["papers"].get(self.paper)
            if limits is None:
                available = [p for p, v in entry["papers"].items() if v]
                problems.append(
                    f'{self.paper} paper is not available at {self.trim_w}" x '
                    f'{self.trim_h}" for {self.binding}. Available: {available}'
                )
            elif pages is not None:
                if pages < limits["min"]:
                    problems.append(
                        f"{pages} pages is below KDP's minimum of {limits['min']} "
                        f"for this trim and paper. Add front or back matter, or "
                        f"choose a smaller trim size."
                    )
                elif pages > limits["max"]:
                    problems.append(
                        f"{pages} pages exceeds KDP's maximum of {limits['max']} "
                        f"for this trim and paper. Choose a larger trim size, a "
                        f"smaller font, or split the book into volumes."
                    )

        min_font = specs.constants()["interior"]["min_font_pt"]
        if self.font_pt < min_font:
            problems.append(f"Body font {self.font_pt}pt is below KDP's {min_font}pt minimum.")

        if pages is not None:
            m = self.margins(pages)
            if m.text_width(self.trim_w) <= 0 or m.text_height(self.trim_h) <= 0:
                problems.append("Margins leave no room for text at this trim size.")

        return problems

    def require_valid(self, pages=None):
        problems = self.validate(pages)
        if problems:
            raise SpecError("; ".join(problems))

    # -- persistence -----------------------------------------------------
    @classmethod
    def for_book_type(cls, book_type, **overrides):
        """The spec the interview would reach for when the author says "I don't know".

        The class defaults are a legal book, not a good one - 6x9 with no
        contents suits a manual, not a memoir. The per-type table is what the
        interview quotes when it explains a choice, so building from anything
        else means the explanation and the book disagree.
        """
        table = specs.book_defaults()
        if book_type not in table:
            raise SpecError(
                f"Unknown book type {book_type!r}. "
                f"Choose one of: {', '.join(specs.book_types())}."
            )
        row = table[book_type]
        fields = {f.name for f in dataclasses_fields(cls)}

        values = {}
        for key, value in row.items():
            # `*_reason` keys exist so the interview can say *why*; they are
            # prose for a human, not settings.
            if key.endswith("_reason"):
                continue
            if key == "trim":
                values["trim_w"], values["trim_h"] = float(value[0]), float(value[1])
            elif key in fields:
                values[key] = value

        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
