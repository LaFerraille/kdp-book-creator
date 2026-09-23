"""The build, as a function rather than a command.

`cmd_build` used to be the only way to produce a book, and it read its inputs
off an argparse Namespace, reported through `print`, and returned an exit code.
That made the one path that matters - manuscript in, uploadable files out -
impossible to call from anything but a terminal, and impossible to test without
fabricating a Namespace. It is why nothing in the suite started from a file on
disk.

So the pipeline takes a request and returns a result. The CLI keeps the parsing
and the printing, which is all it should ever have owned, and anything else -
a test, a skill, a future web front end - can call `build` and read the answer.
Progress still needs reporting as it happens, since a 300-page render is slow,
so callers pass `on_event` rather than having output forced on them.
"""
import pathlib
from dataclasses import dataclass, field

import yaml

from . import languages
from .bookspec import BookSpec
from .cover import render_cover
from .discovery import normalize_chapter_numbers
from .geometry import CoverGeometry
from .ingest import load_manuscript
from .preflight import preflight_cover, preflight_interior
from .project import output_dir, output_names
from .render_epub import check_epub, render_epub
from .render_print import render_interior


class BuildBlocked(Exception):
    """The build stopped for a reason the author can fix, not a crash."""


@dataclass
class BuildRequest:
    manuscript: str
    spec: BookSpec | None = None
    out: str | None = None
    title: str | None = None
    author: str | None = None
    blurb: str = ""
    cover_template: str = "plain"
    cover_image: str | None = None
    verify_cover: bool = False
    interior: bool = True
    cover: bool = True
    epub: bool = True
    font_fallback: bool = False
    force: bool = False
    # Separate from `force`, which is about missing chapter structure. One flag
    # doing both meant that saying "yes, build this unstructured file" also
    # said "yes, typeset it with the wrong hyphenation", which nobody was
    # asked and nothing in the output would show.
    allow_bad_hyphenation: bool = False


@dataclass
class BuildResult:
    outdir: pathlib.Path
    book: object = None
    spec: BookSpec | None = None
    pages: int | None = None
    interior: pathlib.Path | None = None
    cover: pathlib.Path | None = None
    epub: pathlib.Path | None = None
    settings: pathlib.Path | None = None
    geometry: object = None
    interior_report: object = None
    cover_report: object = None
    epub_problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    renamed_chapters: list = field(default_factory=list)

    @property
    def ok(self):
        """True when nothing produced would be rejected on upload."""
        for report in (self.interior_report, self.cover_report):
            if report is not None and not report.ok:
                return False
        return not self.epub_problems


NO_CHAPTERS = (
    "No chapters were found in this manuscript, and none could be inferred.\n"
    "Building now would produce one continuous block of text with no contents "
    "and an ebook KDP will reject.\n\n"
    "Mark chapter openings with '# Title' (or Heading 1 in Word), or use "
    "--force to build it as a single unbroken section anyway."
)

UNKNOWN_LANGUAGE = (
    "I could not tell what language this manuscript is in, and I will not "
    "guess.\n"
    "Defaulting to English is the one wrong answer with no visible symptom: "
    "the book renders, passes every check, and has its words broken in the "
    "wrong places on every page.\n\n"
    "  kdp build … --language fr\n\n"
    "Languages kdp can set: {supported}."
)


def build(request, on_event=None):
    """Run the whole pipeline. Raises BuildBlocked when the author must decide."""
    say = on_event or (lambda _event, _message: None)
    result = BuildResult(outdir=pathlib.Path("."))

    # The project's own build/ directory, regardless of where the manuscript
    # lives or where the command was run from - one fixed, predictable place.
    # Resolved, not just expanded: the LaTeX engine runs with cwd set to the
    # working directory and is also given it as -output-directory, so a
    # relative --out is interpreted twice and the second one lands nowhere.
    # It failed with "I can't write on file texput.log" and, before the engine
    # gained a timeout, sat waiting for a keypress nobody could give it.
    outdir = (pathlib.Path(request.out) if request.out
              else output_dir(request.manuscript)).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    result.outdir = outdir
    # LaTeX leaves .aux/.log/.tex/.toc beside whatever it renders. They are
    # useful when a build fails and noise when it succeeds, so they go in a
    # hidden working directory and the author's folder holds only deliverables.
    workdir = outdir / ".work"
    workdir.mkdir(exist_ok=True)

    book = load_manuscript(request.manuscript, on_note=result.notes.append)
    for note in result.notes:
        say("note", note)
    result.book = book

    if not book.chapters and not request.force:
        raise BuildBlocked(NO_CHAPTERS)

    spec = request.spec or BookSpec()
    # The manuscript decides the language unless the author said otherwise.
    # Detection is the better authority: a spec built from a book type has no
    # opinion about language, and one saved from an earlier build of a
    # different book should not impose its own.
    if spec.language is None:
        spec.language = book.metadata.language
    if spec.language is None:
        # `or "en"` used to stand here, which threw away the one thing
        # detection was careful to say: that it does not know. A short Polish
        # manuscript built happily and recorded `language: en`.
        raise BuildBlocked(
            UNKNOWN_LANGUAGE.format(supported=", ".join(languages.supported())))
    result.spec = spec
    if request.title:
        book.metadata.title = request.title
    if request.author:
        book.metadata.author = request.author
    if not book.metadata.language:
        book.metadata.language = spec.language

    result.renamed_chapters = normalize_chapter_numbers(book)
    for before, after in result.renamed_chapters:
        say("normalised", f"{before!r} -> {after!r} (your file is unchanged)")

    problems = spec.validate()
    if problems:
        raise BuildBlocked("\n".join(problems))

    if request.cover and request.interior and not book.metadata.title:
        # Checked before the interior, which takes minutes to render. Rendering
        # the cover anyway produced a coloured rectangle with nothing on it,
        # which then passed every geometric check. The title is the author's to
        # give; a book cannot have a cover before it has a name.
        raise BuildBlocked(
            "This manuscript does not say what it is called, so there is "
            "nothing to put on the cover.\n"
            "The title is yours to choose - it is not in the file, and it is "
            "not something to guess from a chapter heading.\n\n"
            "  kdp build … --title \"Your Title\" --author \"Your Name\"\n\n"
            "Or --no-cover to build the interior and the ebook now."
        )

    names = output_names(
        book.metadata.title or pathlib.Path(request.manuscript).stem, spec.binding)

    if request.interior:
        rendered = render_interior(
            book, spec, workdir,
            on_note=lambda message: say("note", message),
            font_fallback=request.font_fallback,
            allow_bad_hyphenation=request.allow_bad_hyphenation,
        )
        result.interior = _place(rendered.path, outdir / names["interior"])
        result.pages = rendered.pages
        say("interior", f"{rendered.pages} pages "
                        f"({rendered.passes} rendering pass(es)) "
                        f"-> {result.interior.name}")
        result.interior_report = preflight_interior(result.interior, spec,
                                                     overfull=rendered.overfull)
        (outdir / names["preflight_interior"]).write_text(
            result.interior_report.to_markdown(), encoding="utf-8")
        say("preflight", result.interior_report.summary())

    if request.cover and result.pages is not None:
        geometry = (CoverGeometry.hardcover if spec.binding == "hardcover"
                    else CoverGeometry.paperback)(
            spec.trim_w, spec.trim_h, result.pages, spec.paper)
        result.geometry = geometry
        cover = render_cover(
            geometry, book.metadata, workdir,
            template=request.cover_template, blurb=request.blurb or "",
            font=spec.font, background=request.cover_image,
        )
        result.cover = _place(cover, outdir / names["cover"])
        say("cover", f"{geometry.summary()} -> {result.cover.name}")
        result.cover_report = preflight_cover(result.cover, geometry)
        (outdir / names["preflight_cover"]).write_text(
            result.cover_report.to_markdown(), encoding="utf-8")
        say("preflight", result.cover_report.summary())

        if request.verify_cover:
            from .cover_calculator import CalculatorUnavailable, verify
            try:
                _, diffs = verify(geometry, spec.paper,
                                  download_template=True, outdir=outdir)
                say("verify", "agrees with KDP's calculator" if not diffs
                              else f"DISAGREES with KDP's calculator: {diffs}")
            except CalculatorUnavailable as exc:
                say("verify", f"skipped: {exc}")

    if request.epub and not book.chapters:
        # Only reachable under --force. The print files are legitimate - a
        # chapterless interior is just an unbroken one - but an EPUB without a
        # content document cannot be made valid, so say that rather than
        # failing the whole build after the PDFs are already on disk.
        say("ebook", "skipped: an ebook needs at least one chapter, and this "
                     "manuscript has none. The print files above are fine.")
    elif request.epub:
        result.epub = render_epub(book, outdir / names["epub"],
                                  foreign_italics=(spec.italic_role == "foreign"))
        result.epub_problems = check_epub(result.epub)
        say("ebook", f"{result.epub.name} "
                     f"({'valid' if not result.epub_problems else result.epub_problems})")

    spec.page_count = result.pages
    result.settings = outdir / names["settings"]
    result.settings.write_text(
        yaml.safe_dump(spec.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return result


def _place(rendered, destination):
    """Move a rendered file into the author's folder under its final name.

    `Path.replace` fails across filesystems, which happens whenever --out points
    at another mount, so fall back to a copy rather than making the output
    location depend on how the machine is partitioned.
    """
    try:
        return rendered.replace(destination)  # rename won't overwrite on Windows
    except OSError:
        import shutil
        shutil.copy2(rendered, destination)
        rendered.unlink(missing_ok=True)
        return destination
