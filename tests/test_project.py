"""Where output goes and what it is called.

Small surface, but it decides whether someone can find their book afterwards.
"""
import pathlib

import pytest

from kdp.preflight import SAFE_FILENAME
from kdp.project import find_manuscripts, output_dir, output_names, slugify


# --- slugs ---------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("L'Été Brûlé", "lete-brule"),
    ("Rouge — Noir", "rouge-noir"),
    ("  Spaced  Out  ", "spaced-out"),
    ("100% Papier!", "100-papier"),
    ("Über Größe", "uber-groe"),
])
def test_slugify_transliterates_to_ascii(raw, expected):
    assert slugify(raw) == expected


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("🚲🌞") == "book"
    assert slugify("") == "book"


def test_slugify_is_bounded():
    assert len(slugify("word " * 100)) <= 60


# --- names ---------------------------------------------------------------
def test_every_generated_name_passes_kdps_filename_rules():
    """The plugin must not produce a file its own preflight rejects."""
    for name in output_names("L'Été Brûlé — Tome 2 🌞").values():
        assert SAFE_FILENAME.match(name), f"{name} would fail preflight"


def test_names_say_which_book_and_which_artifact():
    names = output_names("L'Été Brûlé", "paperback")
    assert names["interior"] == "lete-brule-paperback-interior.pdf"
    assert names["cover"] == "lete-brule-paperback-cover.pdf"
    assert names["epub"] == "lete-brule-ebook.epub"


def test_binding_appears_so_paperback_and_hardcover_do_not_collide():
    """Both bindings of one book are built into the same folder."""
    paperback = output_names("My Book", "paperback")
    hardcover = output_names("My Book", "hardcover")
    assert paperback["interior"] != hardcover["interior"]
    assert paperback["cover"] != hardcover["cover"]


def test_epub_has_no_binding_because_an_ebook_is_not_bound():
    assert "paperback" not in output_names("My Book", "paperback")["epub"]


# --- output location -----------------------------------------------------
def test_output_is_the_projects_own_build_directory():
    """Not beside the manuscript, which can be anywhere on disk."""
    from kdp.project import _repo_root
    assert output_dir() == _repo_root() / "build"


def test_output_dir_does_not_depend_on_the_manuscripts_location(tmp_path):
    """A manuscript living anywhere on disk still builds to the same place."""
    elsewhere = tmp_path / "some" / "other" / "place" / "book.md"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("# C\n\nx\n")
    assert output_dir(elsewhere) == output_dir()


def test_output_dir_is_independent_of_the_working_directory(tmp_path, monkeypatch):
    first = output_dir()
    monkeypatch.chdir(tmp_path)
    assert output_dir() == first


def test_output_dir_is_stable_whether_or_not_a_manuscript_is_given():
    assert output_dir() == output_dir(None)


# --- discovery -----------------------------------------------------------
def test_finds_the_manuscript_and_ranks_it_above_the_readme(tmp_path):
    (tmp_path / "README.md").write_text("# Project\n\n" + "short " * 400)
    (tmp_path / "my-novel.md").write_text("# Chapter\n\n" + "word " * 20000)
    found = find_manuscripts(tmp_path)
    assert found[0].name == "my-novel.md"


def test_ignores_the_build_folder_it_just_wrote(tmp_path):
    """Otherwise a second run offers its own previous output as the input."""
    (tmp_path / "book.md").write_text("# C\n\n" + "word " * 20000)
    build = tmp_path / "build"
    build.mkdir()
    (build / "book.epub").write_text("x" * 50000)
    (build / "extracted.txt").write_text("word " * 20000)
    assert all("build" not in p.parts for p in find_manuscripts(tmp_path))


def test_ignores_files_too_short_to_be_a_book(tmp_path):
    (tmp_path / "note.md").write_text("a quick note")
    assert find_manuscripts(tmp_path) == []


def test_ignores_pdfs_since_they_are_not_accepted_input(tmp_path):
    (tmp_path / "book.pdf").write_bytes(b"%PDF-1.5" + b"x" * 50000)
    assert find_manuscripts(tmp_path) == []


def test_returns_empty_rather_than_raising_on_an_empty_folder(tmp_path):
    assert find_manuscripts(tmp_path) == []


def test_the_build_directory_is_inside_the_project(monkeypatch):
    """It was once next to it, on disk, outside the repository, because the
    root was found from a hard-coded `parents[2]` written for a src/ layout."""
    import kdp
    from kdp.project import output_dir

    monkeypatch.delenv("KDP_BUILD_DIR", raising=False)
    root = pathlib.Path(kdp.__file__).resolve().parent.parent
    assert output_dir() == root / "build"


def test_the_launcher_can_send_output_elsewhere(monkeypatch, tmp_path):
    """Installed as a plugin, the root is a cache folder; bin/kdp points
    output at the user's working directory instead."""
    from kdp.project import output_dir

    monkeypatch.setenv("KDP_BUILD_DIR", str(tmp_path / "build"))
    assert output_dir() == tmp_path / "build"