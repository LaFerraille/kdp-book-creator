"""Work out what kind of manuscript this is, before proposing how to set it.

Two layers, and the split is deliberate:

- **Measured** (this module): everything countable. Dialogue punctuation, scene
  breaks, emphasis density, paragraph rhythm, heading shape, language. Exact,
  fast, free, reproducible.
- **Judged** (subagents, driven by the skill): everything that needs reading.
  Genre, register, what the emphasis is *for*, whether a passage is an epigraph
  or a letter, what front matter the book is missing.

Agents are given this report plus excerpts, never the whole manuscript: a full-length
book does not fit in a context window, and asking an agent to count what a regex
counts exactly is both slower and less accurate.
"""
import random
import re
from dataclasses import dataclass, field

from .ingest import chapters_are_self_numbered, sections_are_self_numbered
from .ir import BlockQuote, Image, Paragraph, Rule

# --- signals -------------------------------------------------------------
DIALOGUE_STYLES = {
    # French and Spanish narrative convention
    "guillemets": re.compile(r"«[^»]{0,400}»"),
    # English convention
    "double_quotes": re.compile(r"[“][^”]{0,400}[”]"),
    # A dash opening a line of speech, common in French and Russian typesetting
    "em_dash": re.compile(r"(?m)^\s*[—–]\s+\S"),
    "straight_quotes": re.compile(r'"[^"]{0,400}"'),
}

EMPHASIS = re.compile(r"(?<!\*)\*([^*\n]{1,80})\*(?!\*)")
STRONG = re.compile(r"\*\*([^*\n]{1,80})\*\*")


@dataclass
class TypographySignals:
    dialogue_style: str | None = None
    dialogue_count: int = 0
    dialogue_breakdown: dict = field(default_factory=dict)
    emphasis_count: int = 0
    strong_count: int = 0
    emphasis_samples: list = field(default_factory=list)
    scene_break_count: int = 0
    avg_paragraph_words: float = 0.0
    long_paragraph_share: float = 0.0


@dataclass
class StructureSignals:
    chapters: int = 0
    sections: int = 0
    subtitled_chapters: int = 0
    chapters_self_numbered: bool = False
    sections_self_numbered: bool = False
    sections_per_chapter: tuple = ()
    words_per_chapter: tuple = ()
    heading_pattern: str = ""


@dataclass
class DiscoveryReport:
    """Everything measurable about a manuscript, for a human and for agents."""
    words: int = 0
    images: int = 0
    language: str | None = None
    language_confidence: str = "none"
    structure: StructureSignals = field(default_factory=StructureSignals)
    typography: TypographySignals = field(default_factory=TypographySignals)
    anomalies: list = field(default_factory=list)
    excerpts: dict = field(default_factory=dict)

    def summary_lines(self):
        """The Stage 0 report: what was found, before anything is asked."""
        s, t = self.structure, self.typography
        lines = [
            f"{s.chapters} chapters, {s.sections} sections, {self.words:,} words, "
            f"{self.images} images",
            f"Language: {self.language or 'undetermined'} ({self.language_confidence} confidence)",
        ]
        if s.subtitled_chapters:
            lines.append(
                f"{s.subtitled_chapters}/{s.chapters} chapters have a subtitle line "
                f"under the title"
            )
        if t.dialogue_style:
            lines.append(
                f"Dialogue uses {t.dialogue_style.replace('_', ' ')} "
                f"({t.dialogue_count} passages)"
            )
        if t.emphasis_count:
            lines.append(f"{t.emphasis_count} italicised phrases, {t.strong_count} bold")
        long = t.long_paragraph_share
        lines.append(f"Paragraphs average {t.avg_paragraph_words:.0f} words"
                     + (f"; {long:.0%} run over 150" if long > 0.05 else ""))
        return lines


# --- measurement ---------------------------------------------------------
def _paragraph_texts(book):
    return [b.text for b in book.all_blocks() if isinstance(b, Paragraph)]


def _measure_typography(book, raw_text):
    t = TypographySignals()

    breakdown = {name: len(rx.findall(raw_text)) for name, rx in DIALOGUE_STYLES.items()}
    t.dialogue_breakdown = {k: v for k, v in breakdown.items() if v}
    if breakdown:
        best = max(breakdown, key=breakdown.get)
        if breakdown[best] >= 5:
            t.dialogue_style = best
            t.dialogue_count = breakdown[best]

    emphases = EMPHASIS.findall(raw_text)
    t.emphasis_count = len(emphases)
    t.strong_count = len(STRONG.findall(raw_text))
    t.emphasis_samples = [e.strip() for e in emphases[:40]]

    t.scene_break_count = sum(1 for b in book.all_blocks() if isinstance(b, Rule))

    paras = _paragraph_texts(book)
    if paras:
        lengths = [len(p.split()) for p in paras]
        t.avg_paragraph_words = sum(lengths) / len(lengths)
        t.long_paragraph_share = sum(1 for n in lengths if n > 150) / len(lengths)
    return t


def _measure_structure(book):
    s = StructureSignals(
        chapters=len(book.chapters),
        sections=sum(len(c.sections) for c in book.chapters),
        subtitled_chapters=sum(1 for c in book.chapters if c.subtitle),
        chapters_self_numbered=chapters_are_self_numbered(book),
        sections_self_numbered=sections_are_self_numbered(book),
    )
    s.sections_per_chapter = tuple(len(c.sections) for c in book.chapters)
    s.words_per_chapter = tuple(
        sum(len(b.text.split()) for b in c.blocks() if isinstance(b, (Paragraph, BlockQuote)))
        for c in book.chapters
    )
    depth = []
    if s.chapters:
        depth.append("# chapter")
    if s.subtitled_chapters:
        depth.append("### subtitle")
    if s.sections:
        depth.append("## section")
    s.heading_pattern = " > ".join(depth)
    return s


def _structural_anomalies(book, structure):
    notes = list(book.stats.anomalies)

    counts = structure.words_per_chapter
    if len(counts) > 2:
        avg = sum(counts) / len(counts)
        runts = [i + 1 for i, n in enumerate(counts) if n < avg * 0.25]
        giants = [i + 1 for i, n in enumerate(counts) if n > avg * 3]
        if runts:
            notes.append(
                f"Chapter(s) {runts} are far shorter than average "
                f"({avg:.0f} words) - front matter or an interlude, perhaps?"
            )
        if giants:
            notes.append(f"Chapter(s) {giants} are more than three times the average length.")

    spread = set(structure.sections_per_chapter)
    if len(spread) > 1 and structure.sections:
        notes.append(
            f"Sections per chapter vary ({min(spread)}-{max(spread)}); "
            f"uneven chapter openings are normal but worth a glance."
        )
    return notes


def _pick_excerpts(book, seed=0, per_kind=3, words=220):
    """Representative passages for agents to read, instead of the whole book.

    Deterministic by seed so two runs give an agent the same evidence and the
    proposals stay stable between them.
    """
    rng = random.Random(seed)
    out = {}

    if book.chapters:
        first = book.chapters[0]
        opening = [b.text for b in first.blocks() if isinstance(b, Paragraph)]
        out["opening"] = " ".join(opening)[: words * 7]

    paras = [p for p in _paragraph_texts(book) if len(p.split()) > 40]
    if paras:
        out["random_prose"] = [
            p[: words * 7] for p in rng.sample(paras, min(per_kind, len(paras)))
        ]

    dialogue = [p for p in _paragraph_texts(book)
                if any(rx.search(p) for rx in DIALOGUE_STYLES.values())]
    if dialogue:
        out["dialogue"] = [
            p[: words * 7] for p in rng.sample(dialogue, min(per_kind, len(dialogue)))
        ]

    emphasised = [p for p in _paragraph_texts(book) if EMPHASIS.search(p)]
    if emphasised:
        out["emphasis_in_context"] = [
            p[: words * 7] for p in rng.sample(emphasised, min(per_kind, len(emphasised)))
        ]

    out["chapter_titles"] = [c.title for c in book.chapters]
    out["chapter_subtitles"] = [c.subtitle for c in book.chapters if c.subtitle][:10]
    out["section_titles"] = [s.title for c in book.chapters for s in c.sections][:20]
    return out


def discover(book, raw_text=None, seed=0):
    """Measure everything measurable about a manuscript."""
    if raw_text is None:
        raw_text = "\n\n".join(
            b.text for b in book.all_blocks() if isinstance(b, (Paragraph, BlockQuote))
        )

    structure = _measure_structure(book)
    report = DiscoveryReport(
        words=book.stats.words,
        images=sum(1 for b in book.all_blocks() if isinstance(b, Image)),
        language=book.metadata.language,
        structure=structure,
        typography=_measure_typography(book, raw_text),
        anomalies=_structural_anomalies(book, structure),
        excerpts=_pick_excerpts(book, seed=seed),
    )
    report.language_confidence = "high" if report.language else "none"
    return report


# --- proposed rules ------------------------------------------------------
@dataclass
class Rule_:
    """One formatting decision, its reason, and where it came from.

    Every proposal carries its evidence so the interview can justify itself
    rather than issuing verdicts: people accept "your chapters already say
    'Chapitre 7', so I won't add a second number" far more readily than
    "chapter numbering: off".
    """
    key: str
    value: object
    reason: str
    evidence: str = ""
    confidence: str = "high"
    source: str = "measured"


def propose_rules(report):
    """Turn measurements into formatting decisions, each with its reasoning.

    Only rules that follow from measurement. Anything needing judgement -
    genre, register, what italics are doing - comes from the agent pass and is
    merged on top of these.
    """
    rules = []
    s, t = report.structure, report.typography

    if s.chapters_self_numbered:
        rules.append(Rule_(
            "number_chapters", False,
            "Your chapter titles already contain their numbers, so adding "
            "another would print 'Chapitre 1. Chapitre 1 — ...' in every running head.",
            evidence=f"e.g. {report.excerpts.get('chapter_titles', ['?'])[0]!r}",
        ))
    if s.sections_self_numbered:
        rules.append(Rule_(
            "number_sections", False,
            "Section titles are numbered already; letting the typesetter add "
            "its own would give '1.3  III. La cuve'.",
            evidence=f"e.g. {(report.excerpts.get('section_titles') or ['?'])[0]!r}",
        ))
    if s.subtitled_chapters:
        rules.append(Rule_(
            "chapter_subtitle_style", "centred italic",
            f"{s.subtitled_chapters} of {s.chapters} chapters carry a line under "
            f"the title. Set as a subtitle, it stays out of the table of contents.",
            evidence=", ".join(report.excerpts.get("chapter_subtitles", [])[:2]),
        ))
    if t.dialogue_style == "guillemets":
        rules.append(Rule_(
            "dialogue", "guillemets",
            "Dialogue uses « » and needs French spacing inside the marks; "
            "polyglossia handles that once the language is set.",
            evidence=f"{t.dialogue_count} passages",
        ))
    if t.emphasis_count > 20:
        rules.append(Rule_(
            "emphasis_style", "italic",
            f"{t.emphasis_count} emphasised phrases run through the book; "
            f"they are set in italic rather than bold, which suits running prose.",
            evidence=", ".join(repr(e) for e in t.emphasis_samples[:3]),
        ))
    if t.avg_paragraph_words > 60:
        rules.append(Rule_(
            "paragraph_style", "indented, no extra space",
            f"Paragraphs average {t.avg_paragraph_words:.0f} words. Long prose reads "
            f"better with a first-line indent than with blank lines between paragraphs.",
        ))
    if report.images == 0:
        rules.append(Rule_(
            "interior_ink", "black & white",
            "No images anywhere in the manuscript, so colour printing would add "
            "cost for nothing.",
        ))
    return rules


# --- agent hand-off ------------------------------------------------------
def write_evidence(report, path):
    """Write the packet the exploration agents read.

    Agents get measurements plus excerpts, never the manuscript: a full-length book
    does not fit in a context window, and an agent asked to count what a regex
    already counted will be slower and less accurate. Keeping the exact numbers
    in the packet also stops three agents each inventing their own totals.
    """
    import json
    import pathlib

    s, t = report.structure, report.typography
    payload = {
        "_note": "Counts under 'measured' are exact. Do not recount or contradict them.",
        "measured": {
            "words": report.words,
            "images": report.images,
            "language": report.language,
            "chapters": s.chapters,
            "sections": s.sections,
            "subtitled_chapters": s.subtitled_chapters,
            "heading_pattern": s.heading_pattern,
            "words_per_chapter": list(s.words_per_chapter),
            "sections_per_chapter": list(s.sections_per_chapter),
            "dialogue": t.dialogue_breakdown,
            "italic_phrases": t.emphasis_count,
            "bold_phrases": t.strong_count,
            "avg_paragraph_words": round(t.avg_paragraph_words, 1),
            "scene_breaks": t.scene_break_count,
            "anomalies": report.anomalies,
        },
        "excerpts": report.excerpts,
        "italic_samples": t.emphasis_samples,
    }
    path = pathlib.Path(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# --- normalisation -------------------------------------------------------
_ZERO_PADDED = re.compile(r"(?<![\d])0(\d)(?![\d])")


def normalize_chapter_numbers(book):
    """Strip zero-padding from chapter titles that have it inconsistently.

    Applied to the in-memory book, never to the author's file: the manuscript
    on disk stays exactly as written, and the typeset book is consistent.
    Returns the list of (before, after) changes so the build report can say
    what it did rather than silently altering someone's titles.
    """
    titles = [c.title for c in book.chapters]
    padded = [t for t in titles if _ZERO_PADDED.search(t)]
    unpadded = [t for t in titles if not _ZERO_PADDED.search(t)]
    if not padded or not unpadded:
        return []          # consistently padded, or none at all - leave alone

    changes = []
    for chapter in book.chapters:
        fixed = _ZERO_PADDED.sub(r"\1", chapter.title)
        if fixed != chapter.title:
            changes.append((chapter.title, fixed))
            chapter.title = fixed
    return changes
