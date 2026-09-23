"""Finding the manuscript, and naming what comes out of it.

Two small jobs that decide whether the plugin feels considered or careless.

Someone arrives with a file and wants their book back. They should not have to
say where to put it, and they should not end up with three downloads all called
interior.pdf. Output always goes to the project's own `build/` directory - not
beside the manuscript, which can be anywhere on disk, and not beside the
*terminal*, which is wherever the command happened to be run from - and every
file is named after the book and says what it is.
"""
import os
import pathlib
import re
import unicodedata

MANUSCRIPT_SUFFIXES = (".md", ".markdown", ".txt", ".docx", ".html", ".htm", ".rtf", ".odt")

# Directories that never hold the manuscript someone means.
SKIP_DIRS = {"build", "node_modules", ".git", ".venv", "__pycache__", "dist", ".cache",
             # Reference material that happens to be Markdown. The KDP mirror
             # alone is 281 articles about formatting books, and they outranked
             # the actual manuscript - `find .` offered the author a help page
             # called "format a paperback manuscript" as their book.
             "knowledge", "docs", "site-packages",
             # Skill evaluation runs: previously built books, not new ones.
             "skills"}

# Files that are about a project rather than being the book.
BORING_STEMS = {"readme", "license", "licence", "changelog", "contributing",
                "notes", "todo", "claude", "agents"}

BINDING_WORDS = {"paperback": "paperback", "hardcover": "hardcover"}


def slugify(text, fallback="book"):
    """An ASCII, KDP-safe filename stem.

    KDP rejects file names containing emoji or other unsupported characters, so
    a name taken from a title has to be transliterated - otherwise the plugin's
    own preflight fails the file it just produced. "L'Été Brûlé" becomes
    "lete-brule".
    """
    if not text:
        return fallback
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode()
    ascii_text = re.sub(r"[^\w\s-]", "", ascii_text).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", ascii_text).strip("-")
    return slug[:60].strip("-") or fallback


def _repo_root():
    """The directory holding the `kdp` package, which is the project root.

    Not the manuscript's folder and not the working directory: a plugin
    installed once and used against manuscripts scattered across the disk
    needs one fixed, predictable place for its output, or every run's files
    end up in a different location depending on where someone typed the
    manuscript's path from.

    Derived from this file's position rather than found by searching for a
    marker. It used to walk up looking for pyproject.toml, and dropping the
    build system removed the only thing it was looking for - so every lookup
    fell through to a hard-coded `parents[2]`, written when the package lived
    in src/. From `<root>/kdp/project.py` that is the root's *parent*, so
    `build/` landed outside the repository entirely, next to it on disk, while
    the README promised "the project's own build/ directory" and
    `build/.gitkeep` sat there tracked and unused.
    """
    return pathlib.Path(__file__).resolve().parents[1]


def output_dir(manuscript=None):
    """Where finished files go: ``$KDP_BUILD_DIR``, else ``build/`` at the root.

    Fixed regardless of the manuscript's location, so output is always found in
    the same place. The `bin/kdp` launcher sets KDP_BUILD_DIR to ./build in the
    directory it is run from: installed as a plugin, the repository root is a
    cache folder nobody would think to look in. ``manuscript`` is accepted but
    unused, so call sites that pass it need not change.
    """
    env = os.environ.get("KDP_BUILD_DIR")
    return pathlib.Path(env) if env else _repo_root() / "build"


def output_names(title, binding="paperback", fallback="book"):
    """What each deliverable is called, so a download says which book it is.

    Generic names are fine until someone formats a second book and every file
    in their downloads folder is called interior.pdf.
    """
    slug = slugify(title, fallback)
    bind = BINDING_WORDS.get(binding, binding)
    return {
        "interior": f"{slug}-{bind}-interior.pdf",
        "cover": f"{slug}-{bind}-cover.pdf",
        "epub": f"{slug}-ebook.epub",
        "preflight_interior": f"{slug}-{bind}-interior-preflight.md",
        "preflight_cover": f"{slug}-{bind}-cover-preflight.md",
        "settings": "book.yaml",
    }


def _score(path):
    """How likely is this file to be the book someone means?

    Bigger is better. Word count dominates, because a manuscript is long and a
    README is not, and that single signal separates them more reliably than any
    amount of filename cleverness.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return -1
    score = min(size / 1000, 5000)          # cap so one huge file cannot dwarf the rest
    if path.stem.lower() in BORING_STEMS:
        score -= 4000
    if path.suffix.lower() in (".md", ".docx"):
        score += 200                        # the formats people write books in
    return score


def find_manuscripts(folder=".", limit=8):
    """Candidate manuscripts in a folder, best first.

    The interview confirms the choice rather than assuming it: opening with
    "I found my-book.md, 100,732 words - is that the one?" is a better first
    move than either guessing silently or demanding a path.
    """
    folder = pathlib.Path(folder).resolve()
    candidates = []
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MANUSCRIPT_SUFFIXES:
            continue
        parents = path.relative_to(folder).parts[:-1]
        if any(part in SKIP_DIRS or part.startswith(".") for part in parents):
            continue
        if path.stat().st_size < 2000:      # too short to be a book
            continue
        candidates.append(path)

    candidates.sort(key=_score, reverse=True)
    return candidates[:limit]


# Formats whose bytes are not text. Splitting a zip on whitespace produces a
# number, and printing it as a word count is worse than printing nothing: the
# author reads "about 9,509 words" for a 100,000-word book and has no reason to
# doubt it.
_BINARY_SUFFIXES = {".docx", ".docm", ".odt", ".rtf"}


def describe(path):
    """One line per candidate, for the confirmation prompt."""
    path = pathlib.Path(path)
    try:
        kb = path.stat().st_size / 1024
    except OSError:
        return path.name

    kind = {".docx": "Word document", ".docm": "Word document",
            ".odt": "OpenDocument text", ".rtf": "rich text"}.get(path.suffix.lower())
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return f"{path.name} — {kind} ({kb:.0f} KB)"

    try:
        words = len(path.read_text(encoding="utf-8", errors="replace").split())
        return f"{path.name} — about {words:,} words ({kb:.0f} KB)"
    except OSError:
        return f"{path.name} — {kb:.0f} KB"
