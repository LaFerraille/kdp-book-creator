r"""Resolve a font name to a LaTeX preamble fragment that will actually compile.

A book font is not decoration: it sets the page count, which sets the spine
width, which sets the cover geometry. So the rule here is *resolve or say so* -
never substitute in silence.

The wrinkle is that "installed" means two different things to XeLaTeX. A font
may be a system family that fontconfig can see, or it may ship inside the TeX
distribution as a package, visible to `kpsewhich` but invisible to `fc-list`.
EB Garamond - this project's default for prose - is the second kind on a stock
TinyTeX, which is why `\setmainfont{EB Garamond}` fails on a machine that
demonstrably has the font. Asking the package first fixes that, and is also the
better route when both exist: a font package brings properly hinted small caps,
old-style figures and italic corrections that a bare `\setmainfont` does not.
"""
import functools
import pathlib
import shutil
import subprocess

# Fonts KDP recommends, mapped to the LaTeX package that provides them.
# The package route is tried first - see the module docstring.
FONT_PACKAGES = {
    "eb garamond": "ebgaramond",
    "garamond": "ebgaramond",
    "palatino": "tgpagella",
    "times": "tgtermes",
    "times new roman": "tgtermes",
    "libertinus": "libertinus",
    "linux libertine": "libertine",
    "crimson": "crimson",
    "cormorant garamond": "cormorantgaramond",
}

# Tried in order when the requested font is unavailable. Pagella and Termes are
# Palatino and Times clones - a book set in either still looks like a book -
# and Latin Modern anchors the chain because every TeX installation has it.
FALLBACKS = (
    ("Palatino", "tgpagella"),
    ("Times", "tgtermes"),
    ("Libertinus Serif", "libertinus"),
    ("Latin Modern Roman", "lmodern"),
)


class FontUnavailable(RuntimeError):
    """No usable font, and nothing sensible left to fall back to."""


# Font files a package loads unconditionally. Debian and Ubuntu ship
# ebgaramond.sty without EBGaramond-Initials, so the package looks installed
# and every build then dies inside fontspec.
PACKAGE_REQUIRES = {
    "ebgaramond": "EBGaramond-Initials",
}


def _kpsewhich(name):
    try:
        result = subprocess.run(["kpsewhich", name], capture_output=True,
                                encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


@functools.cache
def _package_exists(package):
    """Is <package>.sty in the TeX tree, with the font files it always loads?"""
    if not shutil.which("kpsewhich") or not _kpsewhich(f"{package}.sty"):
        return False
    # By file name, which XeTeX resolves through the TeX tree only: a copy
    # that fontconfig can see elsewhere does not count.
    required = PACKAGE_REQUIRES.get(package)
    return required is None or any(_kpsewhich(f"{required}{ext}") for ext in (".otf", ".ttf"))


@functools.cache
def _system_font_exists(family):
    """Can fontconfig see this family by name?"""
    if not shutil.which("fc-list"):
        return False
    try:
        result = subprocess.run(["fc-list", "--format", "%{family}\\n"],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    wanted = family.strip().lower()
    for line in result.stdout.splitlines():
        # fontconfig reports comma-separated aliases: "Palatino,Palatino Linotype"
        if any(alias.strip().lower() == wanted for alias in line.split(",")):
            return True
    return False


@functools.cache
def _installed_hyphenation():
    """Pattern sets this TeX installation can actually use.

    language.dat is the list the format was built with, so it is the truth
    about what is loadable - a pattern file sitting in the tree that no format
    has been dumped with is of no use to anyone.
    """
    if not shutil.which("kpsewhich"):
        return frozenset()
    try:
        located = subprocess.run(["kpsewhich", "language.dat"],
                                 capture_output=True, encoding="utf-8", errors="replace",
                                 timeout=15)
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    path = located.stdout.strip()
    if located.returncode != 0 or not path:
        return frozenset()
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return frozenset()

    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        # Entries are "<name> <patternfile> ..." and aliases are "=<name>".
        names.add(line.lstrip("=").split()[0].lower())
    return frozenset(names)


def hyphenation_available(code):
    """Can this language's words actually be hyphenated?

    False for a language this project does not know, which is the answer that
    matters: an unknown code has no pattern set to look for, and treating it as
    English made this return True for every language it could not set.
    """
    from . import languages
    name = languages.hyphenation_name(code)
    return name is not None and name.lower() in _installed_hyphenation()


def hyphenation_hint(code):
    """The command that installs the missing patterns, or None if there is none.

    None when the language is not one this project knows: there is no pattern
    set to name, so there is nothing to tell anyone to install.
    """
    from . import languages
    name = languages.hyphenation_name(code)
    if name is None:
        return None
    # TeX Live names the package after the language, not after the pattern set:
    # ngerman patterns come from hyphen-german.
    package = {"ngerman": "german"}.get(name, name)
    return f"tlmgr install hyphen-{package}"


class Resolution:
    """How a font request was satisfied, and whether the answer is what was asked.

    `note` is None when the request was honoured. When it is not, it explains
    the substitution in the author's terms, because a changed font means a
    changed page count and they need to know before they price the book.
    """

    def __init__(self, requested, resolved, latex, via, note=None):
        self.requested = requested
        self.resolved = resolved
        self.latex = latex
        self.via = via            # "package" | "system" | "fallback"
        self.note = note

    @property
    def substituted(self):
        return self.note is not None

    def __repr__(self):
        return f"<Resolution {self.requested!r} -> {self.resolved!r} via {self.via}>"


def resolve(font, allow_fallback=False):
    """Find a way to set `font`, preferring a LaTeX package over a system family.

    Returns a Resolution whose `.latex` goes straight into the preamble.

    Refusing is the default, and deliberately so: a different font sets a
    different number of pages, which sets a different spine width, so a
    substitution the author did not choose quietly invalidates their cover.
    Callers that would rather have a book than a correct spine can opt in.
    """
    requested = (font or "").strip()
    if not requested:
        # An empty request is not an error: book.yaml can carry `font: ""`.
        # It means "whatever sets a book", which is the head of the chain.
        requested = FALLBACKS[0][0]

    package = FONT_PACKAGES.get(requested.lower())
    if package and _package_exists(package):
        return Resolution(requested, requested,
                          r"\usepackage{%s}" % package, "package")

    if _system_font_exists(requested):
        return Resolution(requested, requested,
                          r"\setmainfont{%s}" % requested, "system")

    # A font we have no package mapping for might still be installed under a
    # name fontconfig spells differently; let XeLaTeX have the last word rather
    # than refusing a font that would in fact have worked.
    if not shutil.which("fc-list") and not package:
        return Resolution(requested, requested,
                          r"\setmainfont{%s}" % requested, "system")

    if not allow_fallback:
        usable = sorted(available_fonts())
        raise FontUnavailable(
            f"{requested} is not installed, and no LaTeX package provides it.\n"
            f"Fonts you can use right now: {', '.join(usable) if usable else 'none found'}.\n"
            f"Install {requested}, choose one of the above, or pass "
            f"--font-fallback to build in a substitute anyway."
        )

    for name, pkg in FALLBACKS:
        if _package_exists(pkg):
            return Resolution(
                requested, name, r"\usepackage{%s}" % pkg, "fallback",
                note=(f"{requested} is not installed, so the book was set in "
                      f"{name} instead. This changes the page count and "
                      f"therefore the spine width. Install {requested} and "
                      f"rebuild if you want it."),
            )
    raise FontUnavailable(
        f"{requested} is not installed, and no fallback font is either.\n"
        f"Your TeX installation looks incomplete - try: tlmgr install lmodern"
    )


def available_fonts():
    """Which of the mapped fonts this machine can actually set. For `kdp doctor`."""
    out = {}
    for name, package in sorted(FONT_PACKAGES.items()):
        if _package_exists(package):
            out[name.title()] = f"package {package}"
        elif _system_font_exists(name):
            out[name.title()] = "system font"
    return out
