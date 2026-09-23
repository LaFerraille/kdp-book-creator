"""Render the Book IR to a print-ready PDF with XeLaTeX.

The one genuinely tricky part is that margins and page count are circular: KDP's
required gutter grows with the page count, but the page count depends on the
gutter. This module resolves that by rendering, counting, and re-rendering when
the count crosses a bracket boundary - a fixed-point iteration that converges in
two or three passes for real manuscripts.
"""
import os
import pathlib
import re
import shutil
import subprocess
import typing

import pikepdf

from . import languages
from .fonts import FontUnavailable, hyphenation_available, hyphenation_hint
from .fonts import resolve as resolve_font
from .geometry import gutter_for_page_count, interior_page_size
from .ingest import chapters_are_self_numbered, sections_are_self_numbered
from .ir import BlockQuote, Image, Lines, ListBlock, Paragraph, Rule
from .latex import inline_to_latex

MAX_PASSES = 5


class Rendered(typing.NamedTuple):
    """What one interior render produced.

    `overfull` carries how far any line ran past the text block, which only the
    typesetter knows - the finished PDF looks geometrically perfect either way.
    """
    path: pathlib.Path
    pages: int
    passes: int
    overfull: tuple = ()


class RenderError(RuntimeError):
    pass


class EngineMissing(RuntimeError):
    pass


def find_engine():
    """Prefer a system XeLaTeX; fall back to Tectonic, which fetches its own packages."""
    for name in ("xelatex", "tectonic"):
        path = shutil.which(name)
        if path:
            return name, path
    raise EngineMissing(
        "No LaTeX engine found. Install one of:\n"
        "  TinyTeX (small):  https://yihui.org/tinytex/\n"
        "  Tectonic:         brew install tectonic\n"
        "  MacTeX (large):   brew install --cask mactex"
    )


# --- document body -------------------------------------------------------
def _render_block(block, italic="textit"):
    if isinstance(block, Paragraph):
        return inline_to_latex(block.text, italic)
    if isinstance(block, BlockQuote):
        return "\\begin{quotation}\n%s\n\\end{quotation}" % inline_to_latex(block.text, italic)
    if isinstance(block, Lines):
        # memoir's verse environment hangs the continuation of a line that is
        # too long for the measure, instead of letting it start flush like a
        # new line. For verse that distinction is the whole point: a reader has
        # to be able to tell a run-over from a line the poet wrote.
        # The empty group after \\ matters: \\ scans ahead for an optional
        # [length], so a following line that opens with a stage direction -
        # "[Enter Barnardo]" - is swallowed as a measurement and LaTeX stops
        # with "Missing number, treated as zero".
        body = " \\\\{}\n".join(inline_to_latex(line, italic) for line in block.lines)
        # The empty group after \begin{verse} is needed for the same reason as
        # the one after \\: memoir's verse takes an optional [length], so a
        # first line opening with a bracket is eaten as an argument.
        return "\\begin{verse}{}\n%s\n\\end{verse}" % body
    if isinstance(block, ListBlock):
        env = "enumerate" if block.ordered else "itemize"
        items = "\n".join(f"  \\item {inline_to_latex(i, italic)}" for i in block.items)
        return f"\\begin{{{env}}}\n{items}\n\\end{{{env}}}"
    if isinstance(block, Image):
        return (
            "\\begin{figure}[htbp]\\centering\n"
            "  \\includegraphics[width=\\linewidth,keepaspectratio]{%s}\n"
            "%s\\end{figure}"
        ) % (block.path,
             f"  \\caption{{{inline_to_latex(block.alt, italic)}}}\n" if block.alt else "")
    if isinstance(block, Rule):
        return "\\pfbreak"
    return ""


def _render_chapter(chapter, italic="textit"):
    out = [f"\\chapter{{{inline_to_latex(chapter.title, italic)}}}"]
    if chapter.subtitle:
        # A subtitle is set under the chapter title, not as a heading, so it
        # stays out of the table of contents and the running heads.
        out.append(f"\\chaptersubtitle{{{inline_to_latex(chapter.subtitle, italic)}}}")
    for block in chapter.preamble:
        out.append(_render_block(block, italic))
    for section in chapter.sections:
        out.append(f"\\section{{{inline_to_latex(section.title, italic)}}}")
        out.extend(_render_block(b, italic) for b in section.blocks)
    return "\n\n".join(b for b in out if b)


# --- preamble ------------------------------------------------------------
def build_latex(book, spec, pages_assumed, font=None):
    """Generate the complete .tex source for one rendering pass.

    `font` is a fonts.Resolution; when omitted it is resolved here, so the
    function stays usable on its own in tests.
    """
    font = font or resolve_font(spec.font)
    m = spec.margins(pages_assumed)
    lang = languages.polyglossia(spec.language)
    meta = book.metadata

    # memoir wants the physical sheet, which is larger than the trim when the
    # book bleeds; the trim itself stays the stock size.
    page = interior_page_size(spec.trim_w, spec.trim_h, bleed=spec.bleed)

    parts = [
        r"\documentclass[%gpt,twoside,openright]{memoir}" % spec.font_pt,
        r"\usepackage{fontspec}",
        r"\usepackage{polyglossia}",
        r"\usepackage{graphicx}",
        r"\usepackage{microtype}",
        r"\setmainlanguage{%s}" % lang,
        # A line TeX cannot break - a URL, a long proper noun, a word whose
        # language has no patterns - otherwise becomes an overfull box, which
        # is ink outside the text block rather than merely a loose line.
        # Letting the paragraph stretch is the lesser fault by a wide margin.
        r"\tolerance=2000",
        r"\emergencystretch=3em",
        r"\hbadness=2000",
        font.latex,
        "",
        r"\setstocksize{%.4fin}{%.4fin}" % (page.height, page.width),
        r"\settrimmedsize{%.4fin}{%.4fin}{*}" % (spec.trim_h, spec.trim_w),
        r"\settrims{0pt}{0pt}",
        r"\setlrmarginsandblock{%.4fin}{%.4fin}{*}" % (m.inside, m.outside),
        r"\setulmarginsandblock{%.4fin}{%.4fin}{*}" % (m.top, m.bottom),
        r"\checkandfixthelayout",
        "",
        r"\setSingleSpace{%.3f}" % spec.leading_ratio,
        r"\SingleSpacing",
    ]

    parts.append(r"\setlength{\parindent}{%s}"
                 % ("1.5em" if spec.indent_paragraphs else "0pt"))
    if not spec.indent_paragraphs:
        parts.append(r"\setlength{\parskip}{0.6\baselineskip}")

    # When titles already carry their own number ("Chapitre 7 - Le retour",
    # "III. La cuve"), the typesetter must not add another, or
    # headings read "Chapitre 7. Chapitre 7 - Le retour" and "1.3  III. La cuve".
    # Chapters and sections are judged separately; a book may number one only.
    # The spec wins when the author settled it; otherwise read the manuscript.
    self_chapters = (not spec.number_chapters if spec.number_chapters is not None
                     else chapters_are_self_numbered(book))
    self_sections = (not spec.number_sections if spec.number_sections is not None
                     else sections_are_self_numbered(book))
    if self_chapters:
        parts += [
            "",
            r"\renewcommand{\printchaptername}{}",
            r"\renewcommand{\printchapternum}{}",
            r"\renewcommand{\afterchapternum}{}",
        ]
    if self_chapters and self_sections:
        parts.append(r"\setsecnumdepth{part}")     # number nothing below part
    elif self_sections:
        parts.append(r"\setsecnumdepth{chapter}")  # keep chapter numbers only

    # When italics mark foreign words rather than emphasis, suppress
    # hyphenation inside them: the main language's patterns applied to a
    # Spanish or Wolof word break it in the wrong place. Line breaks between
    # words are still allowed, so a long quoted phrase still sets naturally.
    italic = "textit"
    if spec.italic_role == "foreign":
        italic = "foreignphrase"
        parts += [
            "",
            r"\newcommand{\foreignphrase}[1]{%",
            r"  {\hyphenpenalty=10000\exhyphenpenalty=10000\textit{#1}}}",
        ]

    # Chapter subtitles, used for the date lines under chapter titles.
    parts += [
        "",
        r"\newcommand{\chaptersubtitle}[1]{%",
        r"  \begingroup\centering\itshape #1\par\endgroup",
        r"  \vspace{1.2\baselineskip}}",
    ]

    if spec.running_heads:
        parts.append(r"\pagestyle{headings}")
        # After \pagestyle, never before: memoir's headings style installs its
        # own \chaptermark, so an earlier redefinition is simply overwritten and
        # the running head keeps its duplicated number.
        if self_chapters:
            parts.append(r"\renewcommand{\chaptermark}[1]{\markboth{#1}{}}")
        if self_sections:
            parts.append(r"\renewcommand{\sectionmark}[1]{\markright{#1}}")
    else:
        parts.append(r"\pagestyle{plain}")
    if not spec.page_numbers:
        parts.append(r"\pagestyle{empty}")

    # hyperref is deliberately not loaded: KDP rejects files carrying bookmarks
    # or annotations, and that is what it would add. The remaining metadata
    # (/Producer, /CreationDate) is stripped from the finished PDF instead -
    # see _strip_metadata. Doing it in TeX is not an option: XeTeX has no
    # \pdfvariable primitive (that is LuaTeX's) and xdvipdfmx rewrites docinfo
    # after any \special we emit.

    parts += ["", r"\begin{document}"]

    if meta.title:
        parts += [
            r"\thispagestyle{empty}",
            r"\begin{center}",
            r"  \vspace*{0.25\textheight}",
            r"  {\Huge %s}\par" % inline_to_latex(meta.title),
        ]
        if meta.subtitle:
            parts.append(r"  \vspace{1em}{\Large %s}\par" % inline_to_latex(meta.subtitle))
        if meta.author:
            parts.append(r"  \vspace{2em}{\large %s}\par" % inline_to_latex(meta.author))
        parts += [r"\end{center}", r"\cleardoublepage"]

    if spec.toc:
        # A 60-section contents runs to several pages and buries the chapter
        # arc, so listing chapters only is the default.
        depth = "section" if spec.toc_depth == "chapters+sections" else "chapter"
        parts += [r"\settocdepth{%s}" % depth, r"\tableofcontents*", r"\cleardoublepage"]

    parts.append(r"\mainmatter")
    if book.orphan_blocks:
        # Blank-line separated, exactly as inside a chapter. Appended one per
        # entry they were joined with a single newline, which to TeX is not a
        # paragraph break: every block before the first heading - a dedication,
        # an epigraph, a note on the text - ran together into one slab.
        parts.append("\n\n".join(
            rendered for rendered in
            (_render_block(block, italic) for block in book.orphan_blocks)
            if rendered))
    for chapter in book.chapters:
        parts.append(_render_chapter(chapter, italic))

    parts.append(r"\end{document}")
    return "\n".join(p for p in parts if p != "")


# --- engine --------------------------------------------------------------
_PAGES_RE = re.compile(r"Output written on .*?\((\d+) pages?", re.S)
_OVERFULL_RE = re.compile(r"Overfull \\hbox \(([\d.]+)pt too wide\)")


def overfull_boxes(log_text):
    """How far text ran past the text block, in points, worst first.

    TeX already knows this exactly and writes it to the log, so measuring the
    PDF afterwards would be guessing at something we were told. An overfull box
    is ink outside the text block - the "text goes outside the page" that
    geometric preflight cannot see, because the page is the right size.
    """
    return sorted((float(m.group(1)) for m in _OVERFULL_RE.finditer(log_text)),
                  reverse=True)


# A book should never take this long. Without a limit a LaTeX run that stops to
# prompt - which happens even under nonstopmode - hangs the build forever with
# no output, because the engine's stdout is captured.
ENGINE_TIMEOUT_SECONDS = 600


def _run_engine(engine, tex_path, workdir):
    # The engine runs with cwd set to the working directory and is handed that
    # directory again as an output path, so anything relative is resolved twice
    # and lands nowhere. Resolving here keeps every caller safe rather than
    # relying on each one to pass absolute paths.
    tex_path = pathlib.Path(tex_path).resolve()
    workdir = pathlib.Path(workdir).resolve()
    # ...and then handed to the engine relative to that directory. xdvipdfmx
    # derives its font-subset tags from the file it is given, so an absolute
    # path made two builds of the same book in two folders differ byte-wise.
    source = os.path.relpath(tex_path, workdir)
    if engine == "tectonic":
        cmd = ["tectonic", "--keep-logs", "--outdir", ".", source]
    else:
        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error",
               "-output-directory=.", source]

    # A fixed timestamp makes two builds of an unchanged manuscript
    # byte-identical, so any diff in the output is a real change. Without it
    # xdvipdfmx stamps the current time into the PDF and every build differs.
    env = dict(os.environ)
    env.setdefault("SOURCE_DATE_EPOCH", "0")
    env.setdefault("FORCE_SOURCE_DATE", "1")

    try:
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                              cwd=workdir, env=env, timeout=ENGINE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(
            f"{engine} did not finish within {ENGINE_TIMEOUT_SECONDS // 60} "
            f"minutes and was stopped. This usually means it is waiting for "
            f"input because of an error it could not recover from; the log is "
            f"at {workdir}/{tex_path.stem}.log."
        ) from exc


def _page_count(pdf_path, log_text):
    match = _PAGES_RE.search(log_text)
    if match:
        return int(match.group(1))
    # Tectonic does not print that line; count the PDF's page objects instead.
    data = pdf_path.read_bytes()
    counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", data)]
    if counts:
        return max(counts)
    raise RenderError("could not determine the page count of the rendered PDF")


def _explain_hyphenation(code):
    """Why this book cannot be typeset, in the two ways it can fail.

    They are different problems with different answers, and saying so is the
    point: a missing pattern set is something the reader of this message can
    install, while a language this project has never heard of is something only
    it can fix. Running them together as "install hyphen-<code>" sent people to
    a package that does not exist.
    """
    if not languages.is_known(code):
        spoken = code or "this language"
        return (
            f"This manuscript looks like {spoken}, which kdp does not know how "
            f"to typeset.\n"
            f"It would be set with English hyphenation - words broken in the "
            f"wrong places on every page, and long ones not broken at all, "
            f"running past the margin. Nothing in the finished PDF would show "
            f"it.\n\n"
            f"Languages kdp can set: {', '.join(languages.supported())}.\n"
            f"If the manuscript is one of those, say so:  --language fr\n"
            f"Or pass --allow-bad-hyphenation to build it in English anyway."
        )
    spoken = languages.name(code)
    return (
        f"This manuscript is {spoken}, but your TeX installation has no "
        f"{spoken} hyphenation patterns.\n"
        f"Words would be broken in the wrong places on every page, and long "
        f"ones could not break at all - they would run past the margin.\n\n"
        f"  {hyphenation_hint(code)}\n\n"
        f"Or pass --allow-bad-hyphenation to build it anyway."
    )


def render_interior(book, spec, outdir, passes=MAX_PASSES, on_note=None,
                    font_fallback=False, allow_bad_hyphenation=False):
    """Render the interior PDF, settling the margin/page-count fixed point.

    Returns a Rendered. Raises RenderError if the
    iteration does not settle, rather than looping or silently accepting a
    layout whose gutter is wrong for its final length.

    The font is resolved once, up front: it must be identical across passes or
    the page count chases a moving target, and a substitution needs reporting
    before a long render rather than after it.
    """
    engine, _ = find_engine()

    # Checked before anything is rendered, because the failure leaves no trace
    # in the output: polyglossia substitutes English silently, so the book
    # passes every geometric check and is wrong on every page.
    if not allow_bad_hyphenation and not hyphenation_available(spec.language):
        raise RenderError(_explain_hyphenation(spec.language))

    try:
        font = resolve_font(spec.font, allow_fallback=font_fallback)
    except FontUnavailable as exc:
        # Callers expect rendering problems as RenderError; the message is
        # already written for the author, so it passes through unchanged.
        raise RenderError(str(exc)) from exc
    if font.substituted and on_note:
        on_note(font.note)
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    tex_path = outdir / "interior.tex"
    pdf_path = outdir / "interior.pdf"

    assumed = 200            # any legal starting point; the loop corrects it
    history = []

    for attempt in range(1, passes + 1):
        tex_path.write_text(build_latex(book, spec, assumed, font=font),
                            encoding="utf-8")
        # LaTeX needs a second pass for the table of contents and cross
        # references to settle before its page count can be trusted.
        for _ in range(2 if spec.toc else 1):
            result = _run_engine(engine, tex_path, outdir)
        log = (outdir / "interior.log")
        log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""

        # XeLaTeX under -halt-on-error signals real failures through its exit
        # status, and can leave a partial PDF behind from an earlier pass. So a
        # non-zero status is a failure even when a file is sitting there -
        # otherwise a broken render is handed to preflight, which checks page
        # geometry and has no way to know the text is wrong.
        if result.returncode != 0 or not pdf_path.exists():
            raise RenderError(_explain_failure(log_text, result))

        actual = _page_count(pdf_path, log_text)
        history.append((assumed, actual))

        # The layout is only correct if the gutter we typeset with is the one
        # KDP requires for the length we actually produced.
        # Clamped, because a manuscript too short or too long for KDP must
        # still render - preflight is what reports that, with a page count.
        if (gutter_for_page_count(assumed, clamp=True)
                == gutter_for_page_count(actual, clamp=True)):
            _strip_metadata(pdf_path)
            spec.page_count = actual
            return Rendered(pdf_path, actual, attempt,
                            tuple(overfull_boxes(log_text)))

        assumed = actual

    raise RenderError(
        "Margin iteration did not settle after "
        f"{passes} passes: {history}. The page count is oscillating across a "
        "gutter bracket boundary. Nudge the font size or margin generosity to "
        "move it clear of the edge."
    )


def _strip_metadata(pdf_path):
    """Remove document metadata KDP asks submissions not to carry.

    Also drops /CreationDate, which makes two builds of an unchanged manuscript
    byte-identical - so a diff in the output means a real change.
    """
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # set_pikepdf_as_editor=False, or pikepdf stamps its own /Producer on
        # save and we trade xdvipdfmx's metadata for pikepdf's.
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta.clear()
        if "/Info" in pdf.trailer:
            del pdf.trailer["/Info"]
        # Drop the existing /ID too. xdvipdfmx seeds it from the output path, so
        # keeping it would make an otherwise identical book differ between two
        # build directories. Removing it lets pikepdf derive one from content.
        if "/ID" in pdf.trailer:
            del pdf.trailer["/ID"]
        pdf.save(pdf_path, deterministic_id=True)


def _explain_failure(log_text, result):
    """Turn a LaTeX log into something a non-TeX-user can act on."""
    if "Font" in log_text and "not found" in log_text:
        match = re.search(r"Font \"?([^\"\n]+)\"? not found", log_text)
        name = match.group(1) if match else "the requested font"
        return (
            f"{name} is not installed. Install it, or choose another font - "
            f"KDP recommends Garamond, Palatino, Constantia, Cambria or Centaur. "
            f"Fonts are never substituted silently, because that changes your "
            f"page count and therefore your spine width."
        )
    errors = [ln for ln in log_text.split("\n") if ln.startswith("!")]
    if errors:
        return "LaTeX failed:\n  " + "\n  ".join(errors[:5])
    return f"LaTeX produced no PDF.\n{(result.stderr or result.stdout)[-800:]}"
