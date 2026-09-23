"""Check that this machine can actually build a book, and say what is missing.

Most first-run failures in a project like this are environmental, not logical:
no LaTeX engine, a TeX installation missing `memoir`, a font that resolves on
the author's laptop and not on yours. Those surface today as a traceback five
minutes into a render. Finding them up front, with the exact install command,
is the difference between a plugin someone adopts and one they abandon.

Nothing here is fatal on its own: the report distinguishes what blocks a build
from what merely narrows it, because plenty of useful work needs no EPUB
validator and no pandoc.
"""
import importlib
import shutil
import subprocess

from . import fonts

# (class or package file, what stops working without it)
TEX_REQUIREMENTS = [
    ("memoir.cls", "the interior: it is the document class the book is set in"),
    ("fontspec.sty", "any font selection at all"),
    ("polyglossia.sty", "language-correct hyphenation and quotation marks"),
    # polyglossia loads it, but a minimal TeX (TinyTeX) does not install it too.
    ("xpatch.sty", "polyglossia, which will not load without it"),
    ("microtype.sty", "even margins; text still sets without it"),
    ("graphicx.sty", "images in the interior"),
    ("tikz.sty", "the cover, which is drawn rather than typeset"),
]

PYTHON_REQUIREMENTS = [
    ("yaml", "reading book.yaml", True),
    ("pikepdf", "preflight and PDF metadata stripping", True),
    ("lxml", "reading .docx manuscripts", True),
    ("bs4", "building the local KDP wiki", True),
    ("markdownify", "building the local KDP wiki", True),
    ("playwright", "cross-checking geometry against KDP's live calculator", False),
]


class Finding:
    """One checked thing. `blocking` means a build cannot succeed without it."""

    def __init__(self, name, ok, detail, fix="", blocking=True):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.fix = fix
        self.blocking = blocking

    @property
    def icon(self):
        if self.ok:
            return "ok  "
        return "FAIL" if self.blocking else "warn"


def _kpsewhich(target):
    if not shutil.which("kpsewhich"):
        return False
    try:
        r = subprocess.run(["kpsewhich", target], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def _check_engine():
    for name in ("xelatex", "tectonic"):
        path = shutil.which(name)
        if path:
            return Finding("LaTeX engine", True, f"{name} at {path}")
    return Finding(
        "LaTeX engine", False, "none found",
        fix=("Install one:\n"
             "  TinyTeX (small):  https://yihui.org/tinytex/\n"
             "  Tectonic:         brew install tectonic\n"
             "  MacTeX (large):   brew install --cask mactex"),
    )


def _check_tex_packages():
    out = []
    for target, why in TEX_REQUIREMENTS:
        found = _kpsewhich(target)
        stem = target.rsplit(".", 1)[0]
        # microtype is a refinement, not a requirement; everything else is load-bearing.
        blocking = stem != "microtype"
        out.append(Finding(
            f"TeX: {stem}", found,
            "present" if found else f"missing - needed for {why}",
            fix="" if found else f"tlmgr install {stem}",
            blocking=blocking,
        ))
    return out


def _check_fonts():
    usable = fonts.available_fonts()
    findings = [Finding(
        "Book fonts", bool(usable),
        f"{len(usable)} usable: {', '.join(sorted(usable))}" if usable
        else "none of the recommended fonts resolve",
        fix="" if usable else "tlmgr install ebgaramond tex-gyre",
    )]
    # The default in defaults.yaml and BookSpec. If it silently falls back,
    # every page count in the interview is for a different book than the one
    # that gets built, so it is worth calling out by name.
    # allow_fallback, or this raises on exactly the machine it exists to
    # diagnose: `resolve` refuses by default, so `kdp doctor` on a system
    # without EB Garamond replaced the whole report with one font error.
    # With no font at all, even the fallback chain raises; that is the report.
    try:
        resolution = fonts.resolve("EB Garamond", allow_fallback=True)
    except fonts.FontUnavailable:
        findings.append(Finding(
            "Default font (EB Garamond)", False,
            "unavailable, and no fallback font resolves either",
            fix="tlmgr install ebgaramond tex-gyre lmodern"))
        return findings
    findings.append(Finding(
        "Default font (EB Garamond)", not resolution.substituted,
        f"resolves via {resolution.via}" if not resolution.substituted
        else f"unavailable - would fall back to {resolution.resolved}",
        fix="" if not resolution.substituted else "tlmgr install ebgaramond",
        blocking=False,
    ))
    return findings


def _check_hyphenation():
    """Which languages can actually be typeset, as opposed to merely selected.

    Not blocking, because a book in a language whose patterns are present is
    unaffected - but listed per language, because the failure is otherwise
    undetectable: polyglossia falls back to English without a word, and the
    book is wrong on every page while passing every other check.
    """
    from . import languages
    missing = [c for c in languages.supported() if not fonts.hyphenation_available(c)]
    present = [c for c in languages.supported() if c not in missing]
    return Finding(
        "Hyphenation", not missing,
        f"patterns for {', '.join(languages.name(c) for c in present)}"
        + (f"; missing for {', '.join(languages.name(c) for c in missing)}" if missing else ""),
        fix="" if not missing else "\n".join(
            sorted({fonts.hyphenation_hint(c) for c in missing})),
        blocking=False,
    )


def _check_python():
    out = []
    for module, why, required in PYTHON_REQUIREMENTS:
        try:
            importlib.import_module(module)
            found = True
        except ImportError:
            found = False
        out.append(Finding(
            f"python: {module}", found,
            "present" if found else f"missing - needed for {why}",
            fix="" if found else ("uv pip install -r requirements.txt" if required
                                  else "uv pip install -r requirements-dev.txt"),
            blocking=required,
        ))
    return out


def _check_pandoc():
    path = shutil.which("pandoc")
    return Finding(
        "pandoc", bool(path),
        f"at {path}" if path else "missing - .odt, .rtf and .html manuscripts "
                                  "cannot be read (.docx, .md and .txt still can)",
        fix="" if path else "brew install pandoc",
        blocking=False,
    )


def _check_wiki():
    from .wiki import GRAPH
    return Finding(
        "KDP wiki", GRAPH.exists(),
        "built" if GRAPH.exists() else "not built yet - the skill looks KDP's "
                                       "rules up in it rather than guessing",
        fix="" if GRAPH.exists() else "kdp wiki build   (or /kdp-wiki)",
        blocking=False,
    )


def run():
    """Every check, in the order a build would need them."""
    findings = [_check_engine()]
    findings += _check_tex_packages()
    findings += _check_fonts()
    findings.append(_check_hyphenation())
    findings += _check_python()
    findings.append(_check_pandoc())
    findings.append(_check_wiki())
    return findings


def report(findings):
    """Render findings for the terminal. Returns (text, can_build)."""
    lines = []
    for f in findings:
        lines.append(f"  {f.icon}  {f.name} - {f.detail}")
        if f.fix and not f.ok:
            for fixline in f.fix.split("\n"):
                lines.append(f"        {fixline}")

    blocking = [f for f in findings if not f.ok and f.blocking]
    degraded = [f for f in findings if not f.ok and not f.blocking]

    lines.append("")
    if blocking:
        lines.append(f"  {len(blocking)} problem(s) will stop a build: "
                     + ", ".join(f.name for f in blocking))
    elif degraded:
        lines.append(f"  Ready to build. {len(degraded)} optional thing(s) missing: "
                     + ", ".join(f.name for f in degraded))
    else:
        lines.append("  Everything checks out.")
    return "\n".join(lines), not blocking
