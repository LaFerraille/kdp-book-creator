"""Recover headings from a manuscript that has none the Markdown parser can see.

A plain .txt carries structure the same way a printed book does - by convention
rather than by markup. Underlining a title with equals signs, or writing "ACT 1"
on its own line, is obvious to a reader and invisible to a parser that only
knows `#`. Left alone the whole book becomes one undifferentiated block, which
still renders: you get a PDF with no chapter breaks, no table of contents and an
EPUB with an empty spine. That is the worst possible outcome, because it looks
like success.

So this module reads those conventions and rewrites them as ATX headings, then
*says what it did*. The inference is a proposal for the author to confirm, never
a silent correction - a heuristic that quietly reshapes someone's book is worse
than one that asks.
"""
import re

# "===" under a line is a level-1 heading, "---" a level-2 one. This is not a
# heuristic: it is setext, part of Markdown since the original spec, and the
# parser simply never implemented it.
_SETEXT_H1 = re.compile(r"^=+$")
_SETEXT_H2 = re.compile(r"^-+$")

# The words a manuscript uses to announce a division, in the languages this
# tool supports. Kept in one place because two different questions need them:
# "is this line a heading?" (here) and "does this heading already carry its own
# number?" (ingest). While only the first list knew about acts and scenes, a
# play's contents came out reading "2 ACT 1" and "2.1 Scene 1" - the exact
# mistake the skill's own table warns about.
DIVISION_WORDS = (
    "chapter", "chapitre", "capitulo", "cap\u00edtulo", "kapitel", "capitolo",
    "hoofdstuk", "part", "partie", "parte", "teil", "book", "livre", "libro",
    "act", "acte", "acto", "akt", "scene", "sc\u00e8ne", "escena", "szene",
    "prologue", "prologo", "epilogue", "epilogo", "introduction", "preface",
    "pr\u00e9face", "afterword", "appendix", "annexe",
)

_LABELLED = re.compile(
    r"^\s*(?P<label>" + "|".join(DIVISION_WORDS) + r")"
    r"\b[\s.:\u2013\u2014-]*(?P<number>[0-9]+|[IVXLCDM]+)?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

MAX_HEADING_WORDS = 12


class Inference:
    """What was inferred, so the interview can report it and ask.

    `headings` is a list of (level, text) in document order; `method` names the
    convention that produced them, which is what makes the result explicable.
    """

    def __init__(self, text, headings, method):
        self.text = text
        self.headings = headings
        self.method = method

    @property
    def found(self):
        return bool(self.headings)

    def summary(self):
        if not self.found:
            return "No chapter structure could be inferred."
        levels = {}
        for level, _ in self.headings:
            levels[level] = levels.get(level, 0) + 1
        parts = []
        for level in sorted(levels):
            noun = {1: "chapter", 2: "section"}.get(level, f"level-{level} heading")
            parts.append(f"{levels[level]} {noun}{'s' if levels[level] != 1 else ''}")
        return f"Inferred {' and '.join(parts)} from {self.method}."


def _label_of(title):
    """The family a heading belongs to: 'act', 'scene', 'chapter', or None."""
    match = _LABELLED.match(title)
    return match.group("label").lower() if match else None


def _assign_levels(headings):
    """Demote the inner series when headings form two nested families.

    A play reads "ACT 1" then "Scene 1..n" then "ACT 2"; a treatise reads
    "Part I" then "Chapter 1..n". Flattening both to level 1 would produce
    twenty-six chapters where there are five. The outer family is the rarer
    one, and its first member appears before the inner family's first.
    """
    families = {}
    for index, (_, title) in enumerate(headings):
        label = _label_of(title)
        if label:
            families.setdefault(label, []).append(index)

    if len(families) < 2:
        return headings

    # Rank by first appearance, then by rarity: the outer division opens the
    # book and there are fewer of them.
    ranked = sorted(families, key=lambda name: (families[name][0], len(families[name])))
    outer, inner = ranked[0], ranked[1]
    if len(families[outer]) >= len(families[inner]):
        return headings

    out = []
    for level, title in headings:
        label = _label_of(title)
        if label == outer:
            out.append((1, title))
        elif label == inner:
            out.append((2, title))
        else:
            out.append((level, title))
    return out


def _setext_pass(lines):
    """Find titles underlined with === or ---."""
    found = []
    for i, line in enumerate(lines[:-1]):
        title = line.strip()
        underline = lines[i + 1].strip()
        if not title or not underline:
            continue
        # An underline must be at least as committed as the title is long,
        # otherwise a row of dashes used as a scene break turns the sentence
        # above it into a chapter.
        if len(underline) < max(3, len(title) // 2):
            continue
        if _SETEXT_H1.match(underline):
            found.append((i, 1, title))
        elif _SETEXT_H2.match(underline) and len(title.split()) <= MAX_HEADING_WORDS:
            found.append((i, 2, title))
    return found


def _labelled_pass(lines):
    """Find short standalone lines that name a division ('ACT 1', 'Chapter 4')."""
    found = []
    for i, line in enumerate(lines):
        title = line.strip()
        if not title or len(title.split()) > MAX_HEADING_WORDS:
            continue
        # Standalone: blank (or start of file) above and below, so a sentence
        # that merely begins "Chapter 4 was the hardest" is not promoted.
        above = lines[i - 1].strip() if i else ""
        below = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if above or below:
            continue
        if _LABELLED.match(title):
            found.append((i, 1, title))
    return found


def infer(text):
    """Rewrite a structureless manuscript's conventions as ATX headings."""
    lines = text.split("\n")

    hits = _setext_pass(lines)
    method = "underlined titles (=== and ---)"
    consumed_underline = True
    if not hits:
        hits = _labelled_pass(lines)
        method = "standalone chapter and part lines"
        consumed_underline = False

    if not hits:
        return Inference(text, [], "nothing recognisable")

    levelled = _assign_levels([(level, title) for _, level, title in hits])
    by_index = {hit[0]: levelled[n] for n, hit in enumerate(hits)}

    out, skip = [], set()
    for i, line in enumerate(lines):
        if i in skip:
            continue
        if i in by_index:
            level, title = by_index[i]
            out.append("#" * level + " " + title)
            if consumed_underline:
                skip.add(i + 1)
            continue
        out.append(line)

    return Inference("\n".join(out), levelled, method)
