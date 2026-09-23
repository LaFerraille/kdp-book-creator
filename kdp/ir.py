"""The Book intermediate representation.

Every input format parses into this, and every output format renders from it.
That pivot is what keeps four inputs and three outputs from becoming twelve
converters.

The IR is deliberately semantic rather than typographic: it records that
something *is* a chapter subtitle, not that it should be 14pt italic centred.
Presentation belongs to the renderers and the design defaults.
"""
from dataclasses import dataclass, field


# --- leaf blocks ---------------------------------------------------------
@dataclass(frozen=True)
class Paragraph:
    text: str


@dataclass(frozen=True)
class Image:
    path: str
    alt: str = ""


@dataclass(frozen=True)
class BlockQuote:
    text: str


@dataclass(frozen=True)
class ListBlock:
    items: tuple
    ordered: bool = False


@dataclass(frozen=True)
class Lines:
    """A block whose line breaks carry meaning and must survive typesetting.

    Verse is the obvious case - reflowing "To be, or not to be" into a
    justified paragraph destroys the thing the reader came for - but the same
    is true of a cast list, an address, an epigraph or a recipe's ingredients.
    Prose is the format that may be re-broken; these are not.
    """
    lines: tuple = ()


@dataclass(frozen=True)
class Rule:
    """A thematic break: a scene change within a chapter."""


# --- structure -----------------------------------------------------------
@dataclass
class Section:
    title: str
    blocks: list = field(default_factory=list)


@dataclass
class Chapter:
    title: str
    subtitle: str | None = None
    preamble: list = field(default_factory=list)   # blocks before the first section
    sections: list = field(default_factory=list)

    def blocks(self):
        """Every block in reading order, section headings included implicitly."""
        yield from self.preamble
        for section in self.sections:
            yield from section.blocks


# --- book ----------------------------------------------------------------
@dataclass
class Metadata:
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    language: str | None = None
    isbn: str | None = None
    publisher: str | None = None
    year: int | None = None
    rights: str | None = None


@dataclass
class Stats:
    """What Stage 0 of the interview reports back before asking anything."""
    words: int = 0
    chapters: int = 0
    sections: int = 0
    images: int = 0
    anomalies: list = field(default_factory=list)

    def summary(self):
        bits = [
            f"{self.chapters} chapters",
            f"{self.sections} sections",
            f"{self.words:,} words",
            f"{self.images} images",
        ]
        return ", ".join(bits)


@dataclass
class Book:
    metadata: Metadata = field(default_factory=Metadata)
    chapters: list = field(default_factory=list)
    orphan_blocks: list = field(default_factory=list)  # content before any heading
    stats: Stats = field(default_factory=Stats)
    source_path: str | None = None
    # The normalised Markdown this Book was parsed from. Analysis needs the raw
    # text as well as the structure, and re-reading the source file cannot
    # supply it for a .docx - the bytes on disk are not Markdown at all.
    markdown: str = ""

    def all_blocks(self):
        yield from self.orphan_blocks
        for chapter in self.chapters:
            yield from chapter.blocks()
