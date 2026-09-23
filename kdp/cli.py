"""Command line entry point.

The skill drives the conversation; this does the work. Keeping the two apart
means the pipeline is runnable and testable without a model in the loop, and
the skill never has to embed Python.

    kdp analyse  manuscript.md              what is this book?
    kdp build    manuscript.md              interior, cover, ebook, preflight
    kdp check    interior.pdf --spec …      preflight an existing file
    kdp wiki     build | status | search    the local KDP Help Center graph
"""
import argparse
import json
import pathlib
import sys

import yaml

from . import languages, specs
from .bookspec import PAPERS, BookSpec, SpecError
from .cover import CoverError, render_cover
from .discovery import discover, propose_rules, write_evidence
from .fonts import FontUnavailable
from .geometry import CoverGeometry
from .ingest import PandocMissing, UnsupportedFormat, load_manuscript
from .ir import Metadata
from .pipeline import BuildBlocked, BuildRequest, build
from .preflight import preflight_cover, preflight_interior
from .project import describe, find_manuscripts, output_dir, output_names
from .render_epub import EpubError
from .render_print import EngineMissing, RenderError


def _trim(value):
    """--trim 5.5x8.5"""
    try:
        width, height = value.lower().replace(" ", "").split("x")
        return float(width), float(height)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a trim size. Write it as WIDTHxHEIGHT, e.g. 5.5x8.5.") from None


def _spec_from(args):
    """Resolve the book's settings, most specific source winning.

    An explicit flag beats a saved book.yaml, which beats the per-type
    defaults, which beat the class defaults. Returning None hands the decision
    to the pipeline, which needs the manuscript's language to make it.
    """
    overrides = {}
    trim = getattr(args, "trim", None)
    if trim:
        overrides["trim_w"], overrides["trim_h"] = trim
    for name in ("paper", "font", "font_pt", "language"):
        overrides[name] = getattr(args, name, None)
    if getattr(args, "toc", None) is not None:
        overrides["toc"] = args.toc
    overrides = {k: v for k, v in overrides.items() if v is not None}

    if args.spec:
        # Guarded on .exists() before, so a mistyped path was not an error: it
        # fell through to the defaults and built a 6x9 book with none of the
        # settings that were asked for, and exited 0. --spec is the advertised
        # way to rebuild a book exactly, so silently not doing it is the worst
        # available outcome.
        path = pathlib.Path(args.spec)
        if not path.exists():
            raise FileNotFoundError(
                f"No settings file at {path}. --spec takes the book.yaml a "
                f"previous build wrote into its output folder."
            )
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        spec = BookSpec.from_dict(data)
        for key, value in overrides.items():
            setattr(spec, key, value)
        return spec

    if getattr(args, "book_type", None):
        return BookSpec.for_book_type(args.book_type, **overrides)

    return BookSpec(**overrides) if overrides else None


# --- analyse -------------------------------------------------------------
def cmd_analyse(args):
    notes = []
    book = load_manuscript(args.manuscript, on_note=notes.append)
    # book.markdown, not the file: for a .docx the bytes on disk are a zip, and
    # re-reading them as text is how `analyse` used to die on every Word file.
    report = discover(book, raw_text=book.markdown)

    if args.json:
        print(json.dumps({
            "words": report.words,
            "chapters": report.structure.chapters,
            "sections": report.structure.sections,
            "language": report.language,
            "images": report.images,
            "anomalies": report.anomalies,
            "rules": [
                {"key": r.key, "value": r.value, "reason": r.reason, "evidence": r.evidence}
                for r in propose_rules(report)
            ],
        }, ensure_ascii=False, indent=1))
    else:
        for note in notes:
            print(f"  note: {note}")
        print("What I found")
        for line in report.summary_lines():
            print(f"  {line}")
        if report.anomalies:
            print("\nWorth a look")
            for note in report.anomalies:
                print(f"  - {note}")
        print("\nAbout how long it will be")
        for line in _trim_comparison(report):
            print(f"  {line}")
        print("\nProposed formatting rules")
        for rule in propose_rules(report):
            print(f"  {rule.key} = {rule.value!r}")
            print(f"      {rule.reason}")

    if args.evidence:
        path = write_evidence(report, args.evidence)
        print(f"\nEvidence for exploration agents: {path}", file=sys.stderr)
    return 0


# The three trims the interview offers first. A choice is only real if each
# option comes with its consequence, and for a trim size the consequence the
# author cares about is how many pages - and so how thick, and how costly.
INTERVIEW_TRIMS = ((5.0, 8.0), (5.5, 8.5), (6.0, 9.0))


def _trim_comparison(report):
    """One line per candidate trim: page count and spine width."""
    from .estimate import compare_trim_sizes
    from .geometry import spine_width

    estimates = compare_trim_sizes(
        report.words, INTERVIEW_TRIMS,
        language=report.language or "en",
        chapters=report.structure.chapters,
    )
    lines = []
    for (w, h), estimate in estimates.items():
        spine = spine_width(max(estimate.pages, 24), "cream")
        common = "  (most common for prose)" if (w, h) == (5.5, 8.5) else ""
        lines.append(f"{w}x{h}in - about {estimate.pages} pages, "
                     f"spine {spine:.2f}in{common}")
    lines.append("Estimates, not measurements: the build renders and counts.")
    return lines


# --- build ---------------------------------------------------------------
def _say(event, message):
    """Print one pipeline event. The pipeline decides what happened; this
    decides how it looks."""
    print(f"  {event}: {message}" if event != "normalised"
          else f"  normalised {message}")


def cmd_build(args):
    request = BuildRequest(
        manuscript=args.manuscript,
        spec=_spec_from(args),
        out=args.out,
        title=args.title,
        author=args.author,
        blurb=args.blurb or "",
        cover_template=args.cover_template,
        cover_image=args.cover_image,
        verify_cover=args.verify_cover,
        interior=not args.no_interior,
        cover=not args.no_cover,
        epub=not args.no_epub,
        font_fallback=args.font_fallback,
        force=args.force,
        allow_bad_hyphenation=args.allow_bad_hyphenation,
    )
    try:
        result = build(request, on_event=_say)
    except BuildBlocked as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    print(f"\n  all files are in {result.outdir}")
    print("  settings saved to book.yaml - rebuild with --spec")
    return 0 if result.ok else 1


# --- cover ---------------------------------------------------------------
def cmd_cover(args):
    """Build a cover on its own, from a page count that is already known.

    The spine width depends on the page count, which is only known once the
    interior has been rendered - so a cover cannot be built from a manuscript
    alone. Taking the page count from a previous run's book.yaml is what makes
    "redo the cover with a new blurb" a thing you can do without re-rendering
    300 pages.
    """
    spec = BookSpec.from_dict(
        yaml.safe_load(pathlib.Path(args.spec).read_text(encoding="utf-8")))
    pages = args.pages or spec.page_count
    if not pages:
        print("This cover needs a page count: pass --pages, or use a book.yaml "
              "from a build that rendered the interior.", file=sys.stderr)
        return 1
    if not args.title:
        # Same rule as `kdp build`: without it the cover is a blank rectangle
        # that passes every geometric check. book.yaml does not store it.
        print("A cover needs the book's title: pass --title \"Your Title\" "
              "(and --author \"Your Name\"). It is yours to choose, not "
              "something to guess from a chapter heading.", file=sys.stderr)
        return 1

    outdir = pathlib.Path(args.out) if args.out else output_dir(None)
    workdir = outdir / ".work"
    workdir.mkdir(parents=True, exist_ok=True)

    geometry = (CoverGeometry.hardcover if spec.binding == "hardcover"
                else CoverGeometry.paperback)(
        spec.trim_w, spec.trim_h, pages, spec.paper)
    meta = Metadata(title=args.title, author=args.author)
    names = output_names(args.title, spec.binding)

    cover = render_cover(geometry, meta, workdir, template=args.cover_template,
                         blurb=args.blurb or "", font=spec.font,
                         background=args.cover_image)
    # replace, not rename: on Windows rename refuses to overwrite, so redoing
    # a cover with a new blurb failed on the second run.
    cover = cover.replace(outdir / names["cover"])
    print(f"  cover: {geometry.summary()} -> {cover.name}")
    report = preflight_cover(cover, geometry)
    (outdir / names["preflight_cover"]).write_text(report.to_markdown(),
                                                   encoding="utf-8")
    print(f"  preflight: {report.summary()}")

    if args.verify_cover:
        from .cover_calculator import CalculatorUnavailable, verify
        try:
            _, diffs = verify(geometry, spec.paper, download_template=True,
                              outdir=outdir)
            print("  cover geometry vs KDP's calculator: "
                  + ("agrees" if not diffs else f"DISAGREES {diffs}"))
        except CalculatorUnavailable as exc:
            print(f"  cover verification skipped: {exc}")
    return 0 if report.ok else 1


# --- find ----------------------------------------------------------------
def cmd_find(args):
    """List likely manuscripts so the interview can confirm rather than guess."""
    found = find_manuscripts(args.folder)
    if not found:
        print(f"No manuscript found in {pathlib.Path(args.folder).resolve()}.")
        print("Supported: Markdown, plain text, DOCX, HTML. (PDF is not accepted.)")
        return 1
    print(f"Found {len(found)} possible manuscript(s) in "
          f"{pathlib.Path(args.folder).resolve()}:")
    for i, path in enumerate(found, 1):
        print(f"  {i}. {describe(path)}")
        print(f"     {path}")
    return 0


# --- doctor --------------------------------------------------------------
def cmd_doctor(args):
    """Report whether this machine can build a book, before it tries to."""
    from .doctor import report, run
    text, ok = report(run())
    print("Checking what this machine can do")
    print(text)
    return 0 if ok else 1


# --- check ---------------------------------------------------------------
def cmd_check(args):
    spec = BookSpec.from_dict(
        yaml.safe_load(pathlib.Path(args.spec).read_text(encoding="utf-8"))
    ) if args.spec else BookSpec()
    report = preflight_interior(args.pdf, spec)
    print(report.to_markdown())
    return 0 if report.ok else 1


# --- wiki ----------------------------------------------------------------
def cmd_wiki(args):
    from .wiki import GRAPH, TOPICS, graph

    if args.action == "build":
        from .wiki import build, fetch
        from .wiki import specs as wiki_specs
        print("Fetching the KDP Help Center (cached pages are reused) ...")
        fetch.fetch(refresh=args.refresh)
        print("Building topics ...")
        build.build()
        g = graph.build_graph()
        print(f"Graph: {len(g['nodes'])} nodes, {len(g['edges'])} edges -> {GRAPH}")
        if wiki_specs.extract():
            print("NOTE: KDP's trim-size or margin tables changed; "
                  "kdp/specs/trim_sizes.json was regenerated. Review the diff.")
        if args.png:
            graph.render_png(args.png, g)
            print(f"Picture -> {args.png}")
        return 0

    if args.action == "status":
        if not GRAPH.exists():
            print("The KDP wiki is not built. Run: kdp wiki build")
            return 1
        g = graph.load_graph()
        topics = sum(1 for n in g["nodes"] if n["kind"] == "topic")
        print(f"{topics} topics, {len(g['edges'])} edges, fetched {g['fetched_at']}")
        return 0

    hits = graph.search(" ".join(args.query), k=args.k)
    if not hits:
        print("No topic in the KDP wiki matches that. Rephrase, or say the "
              "help centre does not cover it.")
        return 1
    for i, h in enumerate(hits, 1):
        print(f"{i}. {h['title']}  [{h['section']}]  score {h['score']}")
        # Absolute: for a plugin user the wiki lives in the plugin's own
        # directory, not the one they are working in.
        print(f"   {TOPICS / pathlib.Path(h['path']).name}")
        print(f"   {h['source']}")
        if h["neighbours"]:
            print("   linked: " + "; ".join(t for t, _ in h["neighbours"][:6]))
    return 0


# Failures we have something useful to say about. Anything else is a bug and
# should keep its traceback.
EXPECTED_FAILURES = (
    CoverError,
    EngineMissing,
    EpubError,
    FileNotFoundError,
    FontUnavailable,
    PandocMissing,
    RenderError,
    SpecError,
    UnsupportedFormat,
    yaml.YAMLError,
)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kdp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyse", aliases=["analyze"], help="inspect a manuscript")
    a.add_argument("manuscript")
    a.add_argument("--json", action="store_true")
    a.add_argument("--evidence", help="write the agent evidence packet here")
    a.set_defaults(func=cmd_analyse)

    b = sub.add_parser("build", help="produce interior, cover and ebook")
    b.add_argument("manuscript")
    b.add_argument("--out", default=None,
                   help="where to write (default: the project's build/ directory)")
    b.add_argument("--spec", help="book.yaml from a previous run")
    b.add_argument("--book-type", choices=specs.book_types(),
                   help="apply this type's defaults (trim, paper, font, contents)")
    b.add_argument("--trim", type=_trim, metavar="WxH",
                   help="trim size in inches, e.g. 5.5x8.5")
    b.add_argument("--paper", choices=PAPERS)
    b.add_argument("--font")
    b.add_argument("--font-pt", type=float, dest="font_pt")
    b.add_argument("--toc", action=argparse.BooleanOptionalAction, default=None,
                   help="include a table of contents")
    b.add_argument("--title")
    b.add_argument("--author")
    b.add_argument("--blurb", help="back-cover text")
    b.add_argument("--cover-template", default="plain")
    b.add_argument("--cover-image", help="artwork spanning the whole cover")
    b.add_argument("--verify-cover", action="store_true",
                   help="cross-check geometry against KDP's live calculator")
    b.add_argument("--no-interior", action="store_true")
    b.add_argument("--no-cover", action="store_true")
    b.add_argument("--no-epub", action="store_true")
    b.add_argument("--font-fallback", action="store_true",
                   help="substitute an available font instead of refusing "
                        "(changes the page count, and so the spine width)")
    b.add_argument("--language",
                   help="ISO code of the manuscript's language, when it cannot "
                        "be detected (%s)" % ", ".join(languages.supported()))
    b.add_argument("--force", action="store_true",
                   help="build even when no chapter structure was found")
    b.add_argument("--allow-bad-hyphenation", action="store_true",
                   dest="allow_bad_hyphenation",
                   help="typeset in English when the language's hyphenation "
                        "patterns are missing (words break in the wrong places "
                        "on every page, and nothing in the PDF shows it)")
    b.set_defaults(func=cmd_build)

    f = sub.add_parser("find", help="look for a manuscript in a folder")
    f.add_argument("folder", nargs="?", default=".")
    f.set_defaults(func=cmd_find)

    v = sub.add_parser("cover", help="build a cover from a known page count")
    v.add_argument("--spec", required=True, help="book.yaml from a previous run")
    v.add_argument("--pages", type=int, help="override the page count in --spec")
    v.add_argument("--out", default=None)
    v.add_argument("--title")
    v.add_argument("--author")
    v.add_argument("--blurb", help="back-cover text")
    v.add_argument("--cover-template", default="plain")
    v.add_argument("--cover-image", help="artwork spanning the whole cover")
    v.add_argument("--verify-cover", action="store_true")
    v.set_defaults(func=cmd_cover)

    d = sub.add_parser("doctor", help="check this machine can build a book")
    d.set_defaults(func=cmd_doctor)

    c = sub.add_parser("check", help="preflight an existing PDF")
    c.add_argument("pdf")
    c.add_argument("--spec")
    c.set_defaults(func=cmd_check)

    w = sub.add_parser("wiki", help="build or search the local KDP Help Center graph")
    wsub = w.add_subparsers(dest="action", required=True)
    wb = wsub.add_parser("build", help="fetch the help centre and index it as a graph")
    wb.add_argument("--refresh", action="store_true",
                    help="re-download pages already cached")
    wb.add_argument("--png", help="also draw the graph to this PNG file")
    wsub.add_parser("status", help="is the wiki built, and when was it fetched?")
    ws = wsub.add_parser("search", help="which topics answer this question?")
    ws.add_argument("query", nargs="+")
    ws.add_argument("-k", type=int, default=5, help="how many topics to return")
    w.set_defaults(func=cmd_wiki)

    parser.add_argument("--debug", action="store_true",
                        help="show the full traceback on failure")
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except EXPECTED_FAILURES as exc:
        if getattr(args, "debug", False):
            raise
        # These exceptions all carry a message written for the author, not for
        # a developer. A traceback buries it; printing it plainly is the whole
        # point of having written it.
        print(f"\n{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
