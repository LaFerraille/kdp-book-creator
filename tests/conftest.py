"""Fixtures every test can reach, and the manuscripts they are built from.

`tests/fixtures/` holds small manuscripts shaped like real ones: a French
novel with chapter subtitles, guillemets and a self-numbered chapter
heading; the same book as a Word document, generated so it cannot drift; and a
play in plain text whose structure exists only as setext underlines and whose
verse must survive typesetting.
"""
import importlib.util
import pathlib
import shutil

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

HAS_ENGINE = bool(shutil.which("xelatex") or shutil.which("tectonic"))


def _load(name):
    """Import a fixture helper by path; tests/fixtures is data, not a package."""
    spec = importlib.util.spec_from_file_location(name, FIXTURES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_docx = _load("make_docx")


@pytest.fixture(scope="session")
def fixtures_dir():
    return FIXTURES


@pytest.fixture(scope="session")
def novel_fr():
    """A French novel: front matter, chapter subtitles, guillemets."""
    return FIXTURES / "novel-fr.md"


@pytest.fixture(scope="session")
def play_en():
    """A play in plain text: setext underlines, a cast list and verse."""
    return FIXTURES / "play-en.txt"


@pytest.fixture(scope="session")
def novel_fr_docx(tmp_path_factory):
    """The same French manuscript as a Word document.

    Built rather than checked in, so that "the .md and the .docx are the same
    book" is true by construction and the equivalence tests are testing the
    readers rather than the fixture author's patience.
    """
    markdown = (FIXTURES / "novel-fr.md").read_text(encoding="utf-8")
    path = tmp_path_factory.mktemp("docx") / "novel-fr.docx"
    return make_docx.write_docx(path, markdown,
                                title="L'Atelier des Reliures", author="Jeanne Delorme")
