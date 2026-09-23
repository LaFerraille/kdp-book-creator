"""Preflight must be able to FAIL, or it is decoration.

Every check here is exercised against a deliberately broken PDF as well as a
good one. A preflight suite that only ever sees valid input proves nothing.
"""
import pikepdf
import pytest
from conftest import HAS_ENGINE

from kdp.bookspec import BookSpec
from kdp.ingest import parse_markdown
from kdp.ir import Metadata
from kdp.preflight import preflight_interior
from kdp.render_print import render_interior

pytestmark = pytest.mark.skipif(not HAS_ENGINE, reason="no LaTeX engine installed")

# Long enough to clear KDP's 24-page minimum: a shorter fixture makes the
# page-count check fail for the fixture's own reasons and masks real defects.
SAMPLE = "# Chapitre 1\n\n## I. Début\n\n" + ("Du texte français. " * 150 + "\n\n") * 60


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("built")
    book = parse_markdown(SAMPLE, Metadata(title="Test", author="A", language="fr"))
    spec = BookSpec(trim_w=6.0, trim_h=9.0, paper="cream", language="fr", font="Palatino")
    rendered = render_interior(book, spec, out)
    pdf, pages = rendered.path, rendered.pages
    return pdf, spec, pages


def test_a_clean_render_passes_every_error_check(built):
    pdf, spec, _ = built
    report = preflight_interior(pdf, spec)
    assert report.errors == [], report.summary()


def test_report_renders_as_markdown(built):
    pdf, spec, _ = built
    md = preflight_interior(pdf, spec).to_markdown()
    assert "Preflight" in md and "Fonts embedded" in md


# --- each check must be able to fail -------------------------------------
def test_detects_wrong_page_size(built):
    """The spec says 6x9; preflight reads the file and must disagree."""
    pdf, _, _ = built
    wrong = BookSpec(trim_w=5.0, trim_h=8.0, paper="cream")
    report = preflight_interior(pdf, wrong)
    assert any("Page size" in c.name for c in report.errors)


def test_detects_page_count_outside_kdp_limits(built, tmp_path):
    """A two-page file is below KDP's 24-page minimum."""
    pdf, spec, _ = built
    short = tmp_path / "short.pdf"
    with pikepdf.open(pdf) as doc:
        del doc.pages[2:]
        doc.save(short)
    report = preflight_interior(short, spec)
    assert any("Page count" in c.name for c in report.errors)


def test_detects_annotations(built, tmp_path):
    pdf, spec, _ = built
    annotated = tmp_path / "annotated.pdf"
    with pikepdf.open(pdf) as doc:
        doc.pages[0].Annots = doc.make_indirect([
            doc.make_indirect({
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Text"),
                "/Rect": [0, 0, 10, 10],
            })
        ])
        doc.save(annotated)
    report = preflight_interior(annotated, spec)
    assert any("annotation" in c.name.lower() for c in report.errors)


def test_detects_metadata(built, tmp_path):
    pdf, spec, _ = built
    tagged = tmp_path / "tagged.pdf"
    with pikepdf.open(pdf) as doc:
        with doc.open_metadata() as meta:
            meta["dc:title"] = "leftover"
        doc.save(tagged)
    report = preflight_interior(tagged, spec)
    assert any("metadata" in c.name.lower() for c in report.warnings + report.errors)


def test_detects_mixed_page_sizes(built, tmp_path):
    pdf, spec, _ = built
    mixed = tmp_path / "mixed.pdf"
    with pikepdf.open(pdf) as doc:
        doc.pages[1].MediaBox = [0, 0, 200, 400]
        doc.save(mixed)
    report = preflight_interior(mixed, spec)
    assert any("Uniform page size" in c.name for c in report.errors)


def test_detects_an_unsafe_filename(built, tmp_path):
    pdf, spec, _ = built
    bad = tmp_path / "livre 🚲.pdf"
    bad.write_bytes(pdf.read_bytes())
    report = preflight_interior(bad, spec)
    assert any("File name" in c.name for c in report.errors)


def test_ok_is_false_when_any_error_is_present(built):
    pdf, _, _ = built
    report = preflight_interior(pdf, BookSpec(trim_w=5.0, trim_h=8.0))
    assert report.ok is False


def test_warnings_alone_do_not_block_upload(built):
    """Warnings are for a human to weigh, not a gate."""
    pdf, spec, _ = built
    report = preflight_interior(pdf, spec)
    assert report.ok is True


def test_blank_page_check_counts_text_not_stream_size(built):
    """Regression: /Contents can be an array of streams, and reading it as a
    single stream raises. Swallowing that made every page of a full book count
    as blank while the check still looked like it worked."""
    pdf, spec, _ = built
    report = preflight_interior(pdf, spec)
    blank = next(c for c in report.checks if c.name == "Blank pages")
    assert blank.passed, blank.detail
    # A handful of genuine blanks (title verso, a recto chapter start) is
    # expected; the bug reported 100%.
    share = int(blank.detail.split("(")[1].rstrip("%)"))
    assert share < 10, blank.detail


def test_detects_genuinely_blank_pages(built, tmp_path):
    pikepdf_mod = pytest.importorskip("pikepdf")
    pdf, spec, _ = built
    padded = tmp_path / "padded.pdf"
    with pikepdf_mod.open(pdf) as doc:
        for _ in range(len(doc.pages)):
            doc.pages.append(doc.add_blank_page(page_size=(396, 612)))
        doc.save(padded)
    report = preflight_interior(padded, spec)
    check = next(c for c in report.checks if c.name == "Blank pages")
    assert not check.passed, check.detail


# --- things geometric checks cannot see ----------------------------------
def test_overfull_lines_are_reported():
    """The page is the right size whether or not text spills out of it."""
    from kdp.preflight import PreflightReport, _check_overfull

    report = PreflightReport()
    _check_overfull(report, [33.3, 4.0, 0.5])
    check = report.checks[-1]
    assert not check.passed
    assert "33.3pt" in check.detail


def test_a_hairs_overshoot_is_not_worth_reporting():
    from kdp.preflight import PreflightReport, _check_overfull

    report = PreflightReport()
    _check_overfull(report, [0.4, 1.1])
    assert report.checks[-1].passed


def test_an_unmeasured_pdf_is_not_reported_as_clear():
    """`kdp check` has no typesetter's log, and must say so rather than pass.

    It printed "PASS Text inside the margins" over a file nothing had ever
    measured - on exactly the files most likely to have text in the margin,
    since the README sells `kdp check` for PDFs made elsewhere.
    """
    from kdp.preflight import PreflightReport, _check_overfull

    report = PreflightReport()
    _check_overfull(report, None)
    check = report.checks[-1]
    assert not check.passed
    assert "not checked" in check.detail
    # Not knowing is not an error: the file may well be fine.
    assert report.ok


def test_kdp_check_does_not_claim_the_margins_were_measured(built):
    pdf, spec, _ = built
    md = preflight_interior(pdf, spec).to_markdown()
    assert "`INFO` **Text inside the margins**" in md


# --- the barcode zone ----------------------------------------------------
@pytest.fixture(scope="module")
def cover_geometry():
    from kdp.geometry import CoverGeometry
    return CoverGeometry.paperback(6.0, 9.0, 200, "cream")


def _render_cover_with(tmp_path, geometry, extra_tikz=""):
    """A cover, optionally with one more thing drawn on it."""
    from kdp.cover import build_cover_latex
    from kdp.render_print import _run_engine, _strip_metadata, find_engine

    tex = build_cover_latex(geometry, Metadata(title="L'Atelier", author="J. Delorme"))
    tex = tex.replace(r"\end{tikzpicture}", extra_tikz + "\n" + r"\end{tikzpicture}")
    path = tmp_path / "cover.tex"
    path.write_text(tex, encoding="utf-8")
    engine, _ = find_engine()
    for _ in range(2):      # TikZ needs the page shipped out once
        _run_engine(engine, path, tmp_path)
    _strip_metadata(tmp_path / "cover.pdf")
    return tmp_path / "cover.pdf"


def test_a_plain_cover_leaves_the_barcode_zone_clear(tmp_path, cover_geometry):
    from kdp.preflight import preflight_cover

    report = preflight_cover(_render_cover_with(tmp_path, cover_geometry),
                             cover_geometry)
    check = [c for c in report.checks if "Barcode" in c.name][0]
    assert check.passed, check.detail
    assert report.errors == [], report.summary()


def test_text_under_the_barcode_is_an_error(tmp_path, cover_geometry):
    """The guarantee the README made and the code did not keep.

    `grep -c barcode kdp/preflight.py` was 0: the zone was computed, used to
    place the blurb, and never checked against the finished file.
    """
    from kdp.preflight import preflight_cover

    x, y, w, h = cover_geometry.barcode_zone
    pdf = _render_cover_with(
        tmp_path, cover_geometry,
        r"\node[anchor=center,text=fg] at ($(O)+(%.4f,%.4f)$) {ISBN 978-0-00};"
        % (x + w / 2, y + h / 2))

    report = preflight_cover(pdf, cover_geometry)
    check = [c for c in report.checks if "Barcode" in c.name][0]
    assert not check.passed
    assert "under the barcode" in check.detail
    assert not report.ok


def test_text_just_above_the_barcode_zone_is_allowed(tmp_path, cover_geometry):
    """The check must measure, not merely notice that the back panel has type."""
    from kdp.preflight import preflight_cover

    x, y, w, h = cover_geometry.barcode_zone
    pdf = _render_cover_with(
        tmp_path, cover_geometry,
        r"\node[anchor=south,text=fg] at ($(O)+(%.4f,%.4f)$) {A line of blurb.};"
        % (x + w / 2, y + h + 0.25))

    report = preflight_cover(pdf, cover_geometry)
    check = [c for c in report.checks if "Barcode" in c.name][0]
    assert check.passed, check.detail
