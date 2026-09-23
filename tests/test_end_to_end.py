"""Drive the real CLI over real manuscripts, start to finish.

Every other test in this suite builds its input in memory and starts somewhere
in the middle of the pipeline. That left the seam where an author's actual file
becomes uploadable artifacts completely uncovered - which is how the documented
entry point came to be broken without a single test noticing, and how a plain
text manuscript could yield zero chapters, build "successfully", and produce an
EPUB with an empty spine that the validator called valid.

So these start where an author starts: a path to a file.
"""
import pathlib
import re
import zipfile

import pytest
import yaml
from conftest import HAS_ENGINE

from kdp import cli
from kdp.bookspec import BookSpec
from kdp.ingest import load_manuscript
from kdp.latex import inline_to_latex

# The flagship example: the full Folger text of Hamlet (CC BY-NC 3.0), tracked.
HAMLET = pathlib.Path(__file__).resolve().parent.parent / "example" / "hamlet.txt"


def test_hamlet_loads_with_its_real_structure():
    """The cast list and five acts, their scenes as sections."""
    book = load_manuscript(HAMLET)
    assert len(book.chapters) == 6
    assert sum(len(c.sections) for c in book.chapters) == 20


def test_plain_text_structure_is_inferred_and_announced():
    """Inference is a proposal, so it has to be reported, not applied quietly."""
    notes = []
    book = load_manuscript(HAMLET, on_note=notes.append)
    assert book.chapters
    assert any("inferred" in note.lower() for note in notes)


def test_a_manuscript_with_no_structure_is_refused(tmp_path):
    """Better to stop than to ship a blob that looks like a book."""
    flat = tmp_path / "flat.txt"
    flat.write_text("Just prose.\n\nMore prose.\n", encoding="utf-8")
    assert cli.main(["build", str(flat), "--out", str(tmp_path / "out")]) == 1
    assert not list((tmp_path / "out").glob("*.pdf"))


def test_a_legacy_doc_says_so_instead_of_failing_obscurely(tmp_path):
    fake = tmp_path / "old.docx"
    fake.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    assert cli.main(["analyse", str(fake)]) == 2


def test_analyse_works_on_a_binary_format(novel_fr_docx):
    """It used to re-read the raw file as UTF-8, so a .docx could never work."""
    assert cli.main(["analyse", str(novel_fr_docx)]) == 0


def test_doctor_reports_without_crashing():
    assert cli.main(["doctor"]) in (0, 1)


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
def test_hamlet_builds_uploadable_files(tmp_path):
    """The README's example, built the way it says: every preflight check passes."""
    out = tmp_path / "out"
    assert cli.main(["build", str(HAMLET), "--out", str(out),
                     "--book-type", "drama", "--title", "Hamlet",
                     "--author", "William Shakespeare"]) == 0

    epub = next(out.glob("*.epub"))
    assert next(out.glob("*cover.pdf")).exists()
    assert (out / "book.yaml").exists()

    # The EPUB must actually contain the book. An empty spine is well-formed,
    # passes every other check, and has nothing in it to read.
    with zipfile.ZipFile(epub) as z:
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        spine = re.search(r"<spine[^>]*>(.*?)</spine>", opf, re.S).group(1)
        assert len(re.findall(r"<itemref", spine)) == 6

    for report in out.glob("*preflight.md"):
        assert "FAIL" not in report.read_text(encoding="utf-8"), report.name


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
def test_force_builds_the_print_files_and_explains_the_missing_ebook(tmp_path):
    """--force is a real choice, so it should produce what it validly can.

    A chapterless interior is just an unbroken one, and printable. A chapterless
    EPUB cannot be made valid at all. Failing the whole build after both PDFs
    are already on disk would be the worst of both.
    """
    flat = tmp_path / "flat.txt"
    flat.write_text("Some prose.\n\nMore prose.\n", encoding="utf-8")
    out = tmp_path / "out"
    # --language, because three words of prose are not enough to detect one and
    # the pipeline now says so rather than assuming English. --no-cover, because
    # an untitled book is refused a cover before anything renders.
    cli.main(["build", str(flat), "--out", str(out), "--force",
              "--language", "en", "--no-cover"])

    assert next(out.glob("*interior.pdf")).exists()
    assert not list(out.glob("*.epub"))


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
def test_a_relative_out_path_works(tmp_path, monkeypatch):
    """The engine is given the working directory twice - as cwd and as
    -output-directory - so a relative path resolves once and then vanishes."""
    monkeypatch.chdir(tmp_path)
    book = tmp_path / "book.md"
    book.write_text("# One\n\nText.\n\n# Two\n\nMore.\n", encoding="utf-8")

    # The exit code is 1 because a two-page book is under KDP's 24-page floor,
    # which is preflight doing its job. What matters here is that the PDF was
    # produced at all: before the fix the engine died looking for interior.tex.
    cli.main(["build", "book.md", "--out", "relative-out",
              "--language", "en", "--no-cover", "--no-epub"])
    assert next((tmp_path / "relative-out").glob("*interior.pdf")).exists()


def test_a_book_type_does_not_override_the_detected_language(tmp_path):
    """A book type has no opinion about language; the manuscript does.

    When BookSpec defaulted language to "en", building a French manuscript with
    --book-type silently typeset it with English hyphenation: words broken in
    the wrong places throughout, and six extra pages on a 300-page memoir,
    which then moves the spine width and the cover geometry with it.
    """
    from kdp.bookspec import BookSpec
    from kdp.pipeline import BuildRequest, build

    french = tmp_path / "livre.md"
    french.write_text(
        "# Chapitre 1\n\n"
        "La bibliothèque ouvrait à neuf heures, et les lecteurs attendaient déjà "
        "devant la porte avec leurs cartes et leurs cahiers sous le bras.\n",
        encoding="utf-8",
    )
    result = build(BuildRequest(
        manuscript=str(french),
        spec=BookSpec.for_book_type("narrative_nonfiction"),
        out=str(tmp_path / "out"),
        interior=False, cover=False, epub=False,
    ))
    assert result.spec.language == "fr"


# --- the same journey, over the small fixtures in tests/fixtures/ ---------
# The fixtures are a few kilobytes and render to far fewer than KDP's 24-page
# minimum, so preflight reports the page count as an error. That is preflight
# working, and the assertions below say exactly that rather than lowering the
# bar: no check other than the page count may fail.
FIXTURE_CASES = ["novel_fr", "novel_fr_docx", "play_en"]

SHORT_BOOK = "Page count in range"


def _only_failure_is_the_length(report_text):
    failures = [line for line in report_text.splitlines() if "`FAIL`" in line]
    return all(SHORT_BOOK in line for line in failures)


@pytest.mark.parametrize("fixture", FIXTURE_CASES)
def test_a_tracked_fixture_loads_with_its_real_structure(request, fixture):
    book = load_manuscript(request.getfixturevalue(fixture))
    assert len(book.chapters) == 3
    assert book.stats.words > 100


def test_the_tracked_markdown_and_docx_are_the_same_book(novel_fr, novel_fr_docx):
    """The equivalence the whole one-parser design exists to guarantee."""
    md = load_manuscript(novel_fr)
    docx = load_manuscript(novel_fr_docx)

    assert [c.title for c in md.chapters] == [c.title for c in docx.chapters]
    assert [c.subtitle for c in md.chapters] == [c.subtitle for c in docx.chapters]
    assert md.metadata.language == docx.metadata.language == "fr"
    assert md.metadata.title == docx.metadata.title == "L'Atelier des Reliures"

    # The comparison is of what gets set, not of what the IR holds: the two
    # files spell the same thing differently on purpose. Markdown writes a
    # literal asterisk as `\*` and Word writes a bold+italic run, and both used
    # to reach the page as marks the reader could see - a backslash before a
    # number, and a pair of asterisks around a word.
    def typeset(book):
        return [inline_to_latex(b.text)
                for b in book.all_blocks() if hasattr(b, "text")]

    set_text = typeset(md)
    assert set_text == typeset(docx)
    assert any(r"\textbf{\textit{brouillé}}" in line for line in set_text)
    assert not any("textbackslash" in line for line in set_text)


def test_the_tracked_play_has_its_structure_inferred_and_announced(play_en):
    notes = []
    book = load_manuscript(play_en, on_note=notes.append)
    assert [c.title for c in book.chapters] == ["Characters in the Play",
                                                "Act 1", "Act 2"]
    assert [s.title for c in book.chapters for s in c.sections] == [
        "Scene 1", "Scene 2", "Scene 1"]
    assert any("inferred" in note.lower() for note in notes)


def test_the_tracked_plays_verse_keeps_its_line_breaks(play_en):
    """Reflowing verse into a justified paragraph destroys what it is."""
    from kdp.ir import Lines
    book = load_manuscript(play_en)
    verse = [b for b in book.all_blocks() if isinstance(b, Lines)]
    assert verse
    assert any("The hour is late, and later than you think." in b.lines
               for b in verse)


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
@pytest.mark.parametrize("fixture", FIXTURE_CASES)
def test_a_tracked_fixture_builds_uploadable_files(request, tmp_path, fixture):
    out = tmp_path / "out"
    source = request.getfixturevalue(fixture)
    assert cli.main(["build", str(source), "--out", str(out),
                     "--title", "A Test Book", "--author", "A. Author"]) == 1

    assert next(out.glob("*interior.pdf")).exists()
    assert next(out.glob("*cover.pdf")).exists()
    assert next(out.glob("*.epub")).exists()
    assert (out / "book.yaml").exists()

    report = next(out.glob("*interior-preflight.md")).read_text(encoding="utf-8")
    assert _only_failure_is_the_length(report), report
    cover_report = next(out.glob("*cover-preflight.md")).read_text(encoding="utf-8")
    assert "FAIL" not in cover_report, cover_report


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
def test_the_tracked_ebook_contains_every_chapter(tmp_path, novel_fr):
    out = tmp_path / "out"
    cli.main(["build", str(novel_fr), "--out", str(out), "--no-cover"])

    with zipfile.ZipFile(next(out.glob("*.epub"))) as z:
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        spine = re.search(r"<spine[^>]*>(.*?)</spine>", opf, re.S).group(1)
        assert len(re.findall(r"<itemref", spine)) == 3
        assert len([n for n in z.namelist() if "chapter-" in n]) == 3


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
def test_the_tracked_french_book_is_typeset_in_french(tmp_path, novel_fr):
    """Not that polyglossia loaded French - it loads whether or not the
    patterns exist, which is precisely how this shipped unnoticed."""
    from kdp.fonts import hyphenation_available
    if not hyphenation_available("fr"):
        pytest.skip("no French hyphenation patterns on this machine")

    out = tmp_path / "out"
    cli.main(["build", str(novel_fr), "--out", str(out), "--no-cover", "--no-epub"])
    tex = (out / ".work" / "interior.tex").read_text(encoding="utf-8")
    assert r"\setmainlanguage{french}" in tex


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
def test_a_tracked_manuscript_with_no_title_will_not_get_a_cover(tmp_path, play_en):
    """The play states no title anywhere a title can live."""
    out = tmp_path / "out"
    assert cli.main(["build", str(play_en), "--out", str(out)]) == 1
    assert not list(out.glob("*cover*.pdf"))


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a LaTeX engine")
def test_a_tracked_cover_can_be_rebuilt_from_a_saved_page_count(tmp_path, novel_fr):
    out = tmp_path / "out"
    cli.main(["build", str(novel_fr), "--out", str(out),
              "--no-cover", "--no-epub"])

    again = tmp_path / "cover"
    assert cli.main(["cover", "--spec", str(out / "book.yaml"),
                     "--out", str(again), "--title", "L'Atelier des Reliures",
                     "--blurb", "Il part un mardi."]) == 0
    assert next(again.glob("*cover.pdf")).exists()
    # Redoing it into the same folder: on Windows a rename cannot overwrite.
    assert cli.main(["cover", "--spec", str(out / "book.yaml"),
                     "--out", str(again), "--title", "L'Atelier des Reliures",
                     "--blurb", "Il part un jeudi."]) == 0


def test_a_cover_on_its_own_still_needs_a_title(tmp_path, capsys):
    """book.yaml does not carry the title, so `kdp cover` must be given one."""
    spec = tmp_path / "book.yaml"
    spec.write_text(yaml.safe_dump(BookSpec().to_dict()), encoding="utf-8")
    assert cli.main(["cover", "--spec", str(spec), "--pages", "200",
                     "--out", str(tmp_path / "out")]) == 1
    assert "--title" in capsys.readouterr().err
    assert not list((tmp_path / "out").glob("*.pdf"))
