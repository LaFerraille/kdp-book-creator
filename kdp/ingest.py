"""Turn a manuscript in any supported format into the Book IR.

Markdown is the primary format and is parsed directly. DOCX, HTML and plain
text are normalised to Markdown by pandoc first, so there is exactly one
structural parser to reason about and test.

PDF is deliberately unsupported: a PDF stores positioned glyphs, not chapters,
so "extracting structure" from one means guessing. Refusing is more honest than
producing a plausible-looking book with the wrong shape.
"""
import pathlib
import re
import shutil
import statistics
import subprocess

from . import languages, structure
from .docx import DocxError
from .docx import metadata_from as docx_metadata
from .docx import to_markdown as docx_to_markdown
from .ir import (
    BlockQuote,
    Book,
    Chapter,
    Image,
    Lines,
    ListBlock,
    Metadata,
    Paragraph,
    Rule,
    Section,
    Stats,
)

# Handled by pandoc. .docx is deliberately absent: it has a native reader, so
# the format most authors actually use needs no external binary.
PANDOC_FORMATS = {
    ".html": "html",
    ".htm": "html",
    ".rtf": "rtf",
    ".odt": "odt",
}
NATIVE_FORMATS = {".md", ".markdown", ".txt"}
DOCX_FORMATS = {".docx", ".docm"}

# Encodings tried in order for text files. utf-8-sig strips a BOM that would
# otherwise become an invisible first character of the first chapter title;
# cp1252 and latin-1 are what Windows word processors emit when saving "plain
# text", and latin-1 never fails, so it terminates the chain.
TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")

# Checked in order, longest mark first: UTF-32-LE's mark opens with UTF-16-LE's,
# so testing the short one first would decode a UTF-32 file as UTF-16. The
# codec is the endian-agnostic one in each family, which reads the mark for the
# byte order and then removes it - decoding as utf-16-le instead leaves the
# mark in the text as an invisible first character of the first chapter title.
BYTE_ORDER_MARKS = (
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"


class UnsupportedFormat(Exception):
    pass


class PandocMissing(Exception):
    pass


def read_text(path):
    """Read a text manuscript, tolerating the encodings authors actually save.

    Returns (text, encoding). A bare UnicodeDecodeError here would be the first
    thing an author sees, and it tells them nothing they can act on.

    The byte-order mark is consulted before anything is tried, because the
    fallback chain cannot be trusted to get this right: latin-1 decodes any
    byte at all, so a UTF-16 file - which "Save as plain text" on Windows still
    produces - came out as mojibake with a NUL between every letter. It did not
    fail. `analyse` read it and reported "951 words, Language: pt (high
    confidence)". A BOM is a statement of fact about the file and outranks any
    guess made after it.
    """
    raw = pathlib.Path(path).read_bytes()

    for mark, encoding in BYTE_ORDER_MARKS:
        if raw.startswith(mark):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                break      # the mark lied; fall through to the chain

    for encoding in TEXT_ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        # UTF-16 without a BOM still decodes cleanly as cp1252 or latin-1, and
        # the tell is the NUL between every ASCII letter. Nothing in a
        # manuscript contains NULs, so their presence means the decoding is
        # wrong whatever it claims.
        if text.count("\x00") > len(text) // 4:
            for wide in ("utf-16-le", "utf-16-be"):
                try:
                    return raw.decode(wide), wide
                except UnicodeDecodeError:
                    continue
        return text, encoding
    # latin-1 cannot fail, so this is unreachable; kept so the contract is
    # explicit rather than relying on a property of the list above.
    return raw.decode("utf-8", errors="replace"), "utf-8 (with replacements)"




def detect_language(text, min_confidence=3):
    """Best-guess ISO code, or None when the evidence is too thin.

    Returning None matters: the interview confirms a detected language, but for
    an unknown one it must ask rather than silently typeset Hungarian with
    English hyphenation.
    """
    words = re.findall(r"[^\W\d_]+", text.lower(), flags=re.UNICODE)
    if not words:
        return None
    counts = {lang: sum(w in stop for w in words)
              for lang, stop in languages.STOPWORDS.items()}
    best = max(counts, key=counts.get)
    ranked = sorted(counts.values(), reverse=True)
    if ranked[0] < min_confidence or ranked[0] == ranked[1]:
        return None
    return best


# --- markdown parsing ----------------------------------------------------
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
# YAML front matter: metadata, and never body text. Two questions read it -
# "what is this book called?" and "what must the parser not typeset?" - so it
# lives with the parsing patterns rather than with either one of them.
_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n", re.S)
_FM_FIELD = re.compile(r"^(title|subtitle|author|language)\s*:\s*(.+?)\s*$",
                       re.M | re.I)
_IMAGE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<path>[^)\s]+)")
_RULE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")


# Telling verse from hard-wrapped prose. Prose that has been wrapped to a
# column fills the measure - most lines end near the wrap width - and its lines
# begin mid-sentence, so they start lowercase. Verse, a cast list and an
# address all do the opposite: short lines that never reach a common margin,
# each beginning with a capital. Joining those into a paragraph destroys the
# only thing that made them what they are.
VERSE_MIN_LINES = 2
VERSE_CAPITAL_SHARE = 0.6

# Below this, a block of capitalised lines is verse and nothing else needs
# asking. Hamlet's dramatis personae is the case that showed one threshold is
# not enough: its longest cast line - "HAMLET, Prince of Denmark, son of the
# late King Hamlet and Queen Gertrude" - is 73 characters, and one entry runs
# to 119, so the whole cast was reflowed into a prose slab. Past the threshold
# the block has to argue for itself: its *typical* line must still be short,
# and its lines must not all end at a common margin.
VERSE_MAX_LINE = 60
# How close to the longest line the *shortest* must come before the block is
# reading as one wrapped paragraph rather than a list.
VERSE_MEASURE_FILL = 0.75


def _fills_a_measure(para):
    """Do these lines all end near a common right margin?

    That is exactly what hard-wrapped prose is - a paragraph broken at a fixed
    column - and what a cast list, an address or a stanza never is.

    A wrapped paragraph's last line is short by definition, so it is left out
    of the comparison, or every paragraph in the book would look ragged. Only
    when it is short, though: a list whose longest entry happens to come last
    is not a paragraph with a long final line, and dropping it there measured
    the list against itself and called it prose.
    """
    lengths = [len(line) for line in para]
    longest = max(lengths)
    body = lengths[:-1] if lengths[-1] < longest else lengths
    return min(body) >= VERSE_MEASURE_FILL * longest


def _line_breaks_are_meaningful(para):
    """Should this run of lines keep its breaks?

    Deliberately conservative: it must look nothing like wrapped prose, because
    wrongly preserving breaks in a novel is far more visible than wrongly
    joining a couplet.
    """
    if len(para) < VERSE_MIN_LINES:
        return False
    lengths = [len(line) for line in para]
    if max(lengths) > VERSE_MAX_LINE:
        # One long entry among short ones is a list with a long entry. A block
        # whose lines are *mostly* long is prose from a file wrapped wide, and
        # no list is written that way.
        if statistics.median(lengths) > VERSE_MAX_LINE:
            return False
        if _fills_a_measure(para):
            return False
    # A bracketed block is an editorial insertion - a stage direction, an
    # transcript note - that happens to have been wrapped. Its line breaks are
    # an artefact of the source file's width, not the author's intent.
    joined = " ".join(line.strip() for line in para)
    if joined.startswith("[") and joined.endswith("]"):
        return False
    starts = [line.lstrip()[:1] for line in para if line.lstrip()]
    capitalised = sum(1 for c in starts if c.isupper() or not c.isalpha())
    return capitalised / len(starts) >= VERSE_CAPITAL_SHARE


def _blocks_from_lines(lines):
    """Group raw lines into leaf blocks, joining wrapped paragraph lines."""
    blocks, para, items, ordered = [], [], [], False

    def flush_para():
        nonlocal para
        if para:
            if _line_breaks_are_meaningful(para):
                blocks.append(Lines(tuple(line.strip() for line in para)))
            else:
                blocks.append(Paragraph(" ".join(para).strip()))
            para = []

    def flush_list():
        nonlocal items, ordered
        if items:
            blocks.append(ListBlock(tuple(items), ordered))
            items = []

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_para()
            flush_list()
            continue
        if _RULE.match(stripped):
            flush_para()
            flush_list()
            blocks.append(Rule())
            continue
        m = _IMAGE.match(stripped)
        if m:
            flush_para()
            flush_list()
            blocks.append(Image(path=m.group("path"), alt=m.group("alt")))
            continue
        if stripped.startswith(">"):
            flush_para()
            flush_list()
            blocks.append(BlockQuote(stripped.lstrip("> ").strip()))
            continue
        m = _ORDERED.match(line)
        if m:
            flush_para()
            if items and not ordered:
                flush_list()
            ordered = True
            items.append(m.group(1).strip())
            continue
        m = _BULLET.match(line)
        if m:
            flush_para()
            if items and ordered:
                flush_list()
            ordered = False
            items.append(m.group(1).strip())
            continue

        flush_list()
        para.append(stripped)

    flush_para()
    flush_list()
    return blocks


def parse_markdown(text, metadata=None):
    """Parse Markdown into the Book IR.

    Structure rules, in order of application:

    1. `#` opens a chapter.
    2. An `h3` on the line *immediately* after a chapter heading, with no body
       text between them, is that chapter's **subtitle** - not a subsection.
       Real manuscripts use this for dates and epigraphs, and reading it as a
       heading would nest every following section under a phantom parent and
       put the date in the table of contents.
    3. `##` opens a section within the current chapter.
    4. Anything before the first `#` is kept as orphan content rather than
       dropped, so nothing can vanish silently.
    """
    book = Book(metadata=metadata or Metadata())
    # Front matter is metadata and is never body text. Left in, its fences
    # parse as thematic breaks and its fields as a paragraph, so a book opened
    # with a scene break and the line "title: L'Atelier des Reliures
    # author: Jeanne Delorme" set as prose.
    matter = _FRONT_MATTER.match(text)
    if matter:
        text = text[matter.end():]
    lines = text.split("\n")

    # Pass 1: split into (heading_level, heading_text, body_lines) runs.
    runs, current, body = [], None, []
    for line in lines:
        m = _HEADING.match(line)
        if m:
            runs.append((current, body))
            current, body = (len(m.group(1)), m.group(2).strip()), []
        else:
            body.append(line)
    runs.append((current, body))

    # Pass 2: assemble chapters, applying the subtitle rule.
    chapter = None
    for index, (heading, body_lines) in enumerate(runs):
        blocks = _blocks_from_lines(body_lines)

        if heading is None:                      # content before any heading
            book.orphan_blocks.extend(blocks)
            continue

        level, title = heading

        if level == 1:
            chapter = Chapter(title=title)
            book.chapters.append(chapter)
            chapter.preamble.extend(blocks)
            continue

        if chapter is None:                      # a section with no chapter above it
            chapter = Chapter(title=title)
            book.chapters.append(chapter)
            chapter.preamble.extend(blocks)
            continue

        is_subtitle = (
            level == 3
            and chapter.subtitle is None
            and not chapter.sections
            and not chapter.preamble
            and index > 0
            and runs[index - 1][0] is not None
            and runs[index - 1][0][0] == 1
            and not _blocks_from_lines(runs[index - 1][1])
        )
        if is_subtitle:
            chapter.subtitle = title
            chapter.preamble.extend(blocks)
            continue

        chapter.sections.append(Section(title=title, blocks=blocks))

    _promote_italic_subtitles(book)
    book.stats = _analyse(book)
    if book.metadata.language is None:
        book.metadata.language = detect_language(text)
    return book


_WHOLLY_ITALIC = re.compile(r"^\*(?P<text>[^*]+)\*$")
SUBTITLE_MAX_WORDS = 12


def _promote_italic_subtitles(book):
    """Treat a short italic line under a chapter title as that chapter's subtitle.

    The same manuscript expresses this two ways depending on where it came
    from. In Markdown the author writes an `###` line; exported from Word the
    identical line arrives as an italic paragraph, because Word has no notion
    of a subtitle either. Reading only the first spelling means the same book
    typesets differently depending on which file you were handed - and the date
    line ends up in the table of contents.

    Deliberately narrow: the paragraph must be the only thing between the
    chapter title and its first section, and short enough that no one would
    mistake it for prose.
    """
    for chapter in book.chapters:
        if chapter.subtitle is not None or len(chapter.preamble) != 1:
            continue
        block = chapter.preamble[0]
        if not isinstance(block, Paragraph):
            continue
        match = _WHOLLY_ITALIC.match(block.text.strip())
        if not match:
            continue
        text = match.group("text").strip()
        if text and len(text.split()) <= SUBTITLE_MAX_WORDS:
            chapter.subtitle = text
            chapter.preamble.clear()


# Titles that carry their own number: "Chapter 4", "Chapitre 07", "4.", "IV."
_SELF_NUMBERED = re.compile(
    r"^\s*(?:" + "|".join(structure.DIVISION_WORDS) + r")\s*[\s.:\u2013\u2014-]*"
    r"(?:[\d]+|[IVXLCDM]+)\b"
    r"|^\s*\d+\s*[.):\u2014\u2013-]"
    r"|^\s*[IVXLC]+\s*[.):\u2014\u2013-]",
    re.IGNORECASE,
)


def _titles_are_self_numbered(titles, threshold=0.6):
    if not titles:
        return False
    hits = sum(bool(_SELF_NUMBERED.match(t)) for t in titles)
    return hits / len(titles) >= threshold


def chapters_are_self_numbered(book, threshold=0.6):
    """Do the chapter titles already contain their own numbering?

    If they do, the typesetter must not add its own, or every chapter opening
    and running head reads "Chapitre 1. Chapitre 1 - La boutique".
    A threshold rather than all-or-nothing, because a book often has one
    unnumbered chapter (a prologue) among numbered ones.
    """
    return _titles_are_self_numbered([c.title for c in book.chapters], threshold)


def sections_are_self_numbered(book, threshold=0.6):
    """The same question for section titles, which number independently.

    A manuscript that numbers its sections with Roman numerals ("I.", "II.")
    and leaves LaTeX's numbering on gets "1.3  III. La cuve". Chapters and
    sections have to be judged separately: a book may well number one and not
    the other.
    """
    titles = [s.title for c in book.chapters for s in c.sections]
    return _titles_are_self_numbered(titles, threshold)


# --- analysis ------------------------------------------------------------
# How many words each kind of block contributes. A table rather than a chain
# of isinstance checks because the chain is exactly what went wrong: `Lines`
# was added to the IR and to every renderer, and missed here, so a play in
# verse reported 10,049 words against an actual 32,004 - a threefold
# undercount, which made `analyse` promise a 36-page book that renders to 203.
# tests/test_ingest.py asserts this table covers every block type the IR
# defines, so the next one cannot be forgotten in the same way.
_WORDS_IN = {
    Paragraph: lambda block: len(block.text.split()),
    BlockQuote: lambda block: len(block.text.split()),
    Lines: lambda block: sum(len(line.split()) for line in block.lines),
    ListBlock: lambda block: sum(len(item.split()) for item in block.items),
    # Alt text describes the picture; it is not part of the book's prose, and
    # counting it would inflate the page estimate for an illustrated book.
    Image: lambda block: 0,
    Rule: lambda block: 0,
}


def _count_words(block):
    counter = _WORDS_IN.get(type(block))
    return counter(block) if counter else 0


def _analyse(book):
    stats = Stats(
        chapters=len(book.chapters),
        sections=sum(len(c.sections) for c in book.chapters),
    )
    for block in book.all_blocks():
        stats.words += _count_words(block)
        if isinstance(block, Image):
            stats.images += 1

    stats.anomalies = _find_anomalies(book)
    return stats


def _find_anomalies(book):
    """Things worth mentioning in Stage 0 rather than silently normalising."""
    notes = []

    # Zero-padded chapter numbers mixed with unpadded ones ("Chapitre 07").
    padded = [c.title for c in book.chapters
              if re.search(r"\b0\d\b", c.title)]
    unpadded = [c.title for c in book.chapters
                if re.search(r"\b[1-9]\d?\b", c.title) and not re.search(r"\b0\d\b", c.title)]
    if padded and unpadded:
        notes.append(
            f"Inconsistent chapter numbering: {len(padded)} zero-padded "
            f"(e.g. {padded[0]!r}) alongside unpadded ones."
        )

    if book.orphan_blocks:
        notes.append(
            f"{len(book.orphan_blocks)} block(s) appear before the first chapter "
            f"heading; they will be treated as front matter."
        )

    empty = [c.title for c in book.chapters if not any(True for _ in c.blocks())]
    if empty:
        notes.append(f"{len(empty)} chapter(s) contain no text: {empty[:3]}")

    return notes


# --- the book's own title ------------------------------------------------
def title_from(text):
    """The title and author a manuscript states about itself, if it does.

    Only places a title actually lives are consulted. A chapter heading is
    never one of them: taking the last chapter of a memoir named the book
    after that chapter. Nor is a proper noun that recurs in the prose: a name
    can appear many times, always mid-sentence, and a tool cannot tell a
    title from any other capitalised name.

    Returning nothing is the useful answer when the file says nothing. The
    title is the author's to give, and asking beats inventing.
    """
    found = {}

    matter = _FRONT_MATTER.match(text)
    if matter:
        for key, value in _FM_FIELD.findall(matter.group(1)):
            found[key.lower()] = value.strip().strip("\"'")
        text = text[matter.end():]

    if "title" not in found:
        # A lone level-1 heading standing above every other heading, with no
        # prose between it and the next one, is a title page written in
        # Markdown. A level-1 heading followed by body text is chapter one.
        lines = text.split("\n")
        headings = [(i, len(m.group(1)), m.group(2).strip())
                    for i, line in enumerate(lines)
                    if (m := _HEADING.match(line))]
        if len(headings) >= 2 and headings[0][1] == 1 and headings[1][1] == 1:
            # The next heading must be another chapter. When it is deeper, the
            # first heading is a chapter and what follows is its subtitle or
            # its first section - the shape every chapter in a memoir has.
            first, nxt = headings[0], headings[1]
            between = [ln for ln in lines[first[0] + 1:nxt[0]] if ln.strip()]
            # And a title that numbers itself is a chapter whatever its level.
            if not between and not _SELF_NUMBERED.match(first[2]):
                found["title"] = first[2]

    return found


# --- loading -------------------------------------------------------------
def _pandoc_to_markdown(path, fmt):
    if not shutil.which("pandoc"):
        raise PandocMissing(
            f"Reading {path.suffix} files needs pandoc, which is not installed.\n"
            f"  macOS:  brew install pandoc\n"
            f"  Linux:  apt install pandoc\n"
            f"Markdown and plain text work without it."
        )
    result = subprocess.run(
        ["pandoc", "--from", fmt, "--to", "markdown-smart", "--wrap=none", str(path)],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pandoc failed on {path.name}: {result.stderr.strip()}")
    return result.stdout


def _sniff(path):
    """What this file really is, regardless of what it is called.

    Extensions lie - a .doc renamed to .docx is common enough that trusting the
    suffix produces a baffling zip error instead of "re-save this as .docx".
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
    except OSError:
        return None
    if head.startswith(_OLE2_MAGIC):
        return "ole2"
    if head.startswith(_ZIP_MAGIC):
        return "zip"
    return None


def load_manuscript(path, metadata=None, on_note=None):
    """Load any supported manuscript into the Book IR.

    `on_note` receives messages about anything that was inferred or worked
    around - a non-UTF-8 encoding, headings recovered from a plain text file.
    They are reported rather than applied silently because each one is a guess
    about the author's intent that they should get to overrule.
    """
    path = pathlib.Path(path)
    note = on_note or (lambda _message: None)

    if not path.exists():
        raise FileNotFoundError(
            f"No manuscript at {path}. Check the path, or run `kdp find .` to "
            f"see what is in the folder."
        )

    suffix = path.suffix.lower()
    actual = _sniff(path)

    if actual == "ole2":
        raise UnsupportedFormat(
            f"{path.name} is a legacy Word document (.doc), whatever its name "
            f"says. Open it in Word or LibreOffice and save it as .docx, then "
            f"try again."
        )

    if suffix == ".pdf":
        raise UnsupportedFormat(
            "PDF is not accepted as input. A PDF records positioned glyphs, not "
            "chapters, so its structure can only be guessed at. Export your "
            "manuscript to DOCX or Markdown instead."
        )

    declared = {}
    if suffix in DOCX_FORMATS or (actual == "zip" and suffix not in PANDOC_FORMATS):
        try:
            text = docx_to_markdown(path)
            declared = docx_metadata(path)
        except DocxError as exc:
            raise UnsupportedFormat(str(exc)) from exc
    elif suffix in NATIVE_FORMATS:
        text, encoding = read_text(path)
        if encoding != "utf-8":
            note(f"{path.name} is not UTF-8; read it as {encoding}.")
    elif suffix in PANDOC_FORMATS:
        text = _pandoc_to_markdown(path, PANDOC_FORMATS[suffix])
    else:
        raise UnsupportedFormat(
            f"{suffix or path.name} is not supported. "
            f"Use Markdown, DOCX, HTML or plain text."
        )

    # Files saved on Windows end their lines with CRLF, and every pattern
    # below expects a bare newline: the front matter went unread and was set
    # as the book's first paragraph.
    text = text.replace("\r\n", "\n")
    book = parse_markdown(text, metadata=metadata)

    # A manuscript with no headings at all is almost never a book with no
    # chapters - it is a book whose chapter markers this parser cannot see.
    # Inferring them is a proposal, which is why it is announced.
    #
    # This runs before the metadata below, not after. Re-parsing produces a
    # fresh Book, so a title read out of the front matter and written onto the
    # first one was simply thrown away, and the author was told "this
    # manuscript does not say what it is called" by a file that says so on its
    # first line. Two of this pipeline's own features colliding.
    if not book.chapters:
        inference = structure.infer(text)
        if inference.found:
            note(inference.summary() + " Confirm before building.")
            text = inference.text
            book = parse_markdown(text, metadata=metadata)

    # What the file says about itself, unless the caller already knows better.
    stated = dict(declared)
    stated.update(title_from(text))
    for field in ("title", "subtitle", "author", "language"):
        if stated.get(field) and not getattr(book.metadata, field, None):
            setattr(book.metadata, field, stated[field])

    book.source_path = str(path)
    book.markdown = text
    return book
