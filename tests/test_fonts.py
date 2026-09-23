"""Resolving a font, and knowing whether a language can be hyphenated.

Both answers change the finished book in ways no later check can see. A
substituted font changes the page count and therefore the spine width; missing
hyphenation patterns change every line break in the book. So this module's
contract is "resolve or say so", and these are the tests of the "or say so".

Every check here is hermetic: what is installed on the machine running the
suite is exactly what must not decide whether these pass.
"""
import pytest

from kdp import fonts, languages


@pytest.fixture
def machine(monkeypatch):
    """A TeX installation we describe, rather than the one under the test.

    Returns a function taking the packages present and the hyphenation pattern
    sets loaded. fontconfig is present and sees nothing, which is the case that
    makes `resolve` refuse rather than defer to XeLaTeX.
    """
    def setup(packages=(), hyphenation=("english",), system_fonts=()):
        monkeypatch.setattr(fonts, "_package_exists", lambda p: p in packages)
        monkeypatch.setattr(fonts, "_system_font_exists",
                            lambda f: f.lower() in {s.lower() for s in system_fonts})
        monkeypatch.setattr(fonts, "_installed_hyphenation",
                            lambda: frozenset(hyphenation))
        monkeypatch.setattr(fonts.shutil, "which",
                            lambda name: "/usr/bin/" + name)
    return setup


# --- hyphenation ---------------------------------------------------------
@pytest.mark.parametrize("code", ["hu", "pl", "nl", "tr", "zz"])
def test_a_language_we_cannot_set_is_not_available(machine, code):
    """The guard that did not guard.

    `hyphenation_name` answered "english" for anything outside the table, and
    English patterns are installed everywhere, so this returned True for every
    language the project cannot typeset. A build with `language: hu` completed
    and emitted \\setmainlanguage{english}: right page size, right trim, fonts
    embedded, and wrong on every page.
    """
    machine(hyphenation=("english", "french", "ngerman"))
    assert fonts.hyphenation_available(code) is False
    assert fonts.hyphenation_hint(code) is None


def test_a_known_language_with_patterns_is_available(machine):
    machine(hyphenation=("english", "french"))
    assert fonts.hyphenation_available("fr") is True


def test_a_known_language_without_patterns_is_not(machine):
    machine(hyphenation=("english",))
    assert fonts.hyphenation_available("fr") is False
    assert fonts.hyphenation_hint("fr") == "tlmgr install hyphen-french"


def test_the_hint_names_the_package_not_the_pattern_set(machine):
    """TeX Live ships ngerman patterns in a package called hyphen-german."""
    machine(hyphenation=("english",))
    assert fonts.hyphenation_hint("de") == "tlmgr install hyphen-german"


def test_every_supported_language_can_be_asked_about(machine):
    """No supported language may reach a caller as None; that means "unknown"."""
    machine(hyphenation=("english",))
    for code in languages.supported():
        assert fonts.hyphenation_hint(code).startswith("tlmgr install hyphen-")


# --- resolving a font ----------------------------------------------------
def test_an_empty_font_request_resolves(machine):
    """`font: ""` in book.yaml raised NameError: FALLBACK.

    The constant had been renamed to FALLBACKS and one reference missed. It is
    the clearest possible proof this module had no test: the line is reached by
    a single empty string in a settings file.
    """
    machine(packages=("tgpagella",))
    resolution = fonts.resolve("")
    assert resolution.resolved == "Palatino"
    assert not resolution.substituted


def test_a_package_is_preferred_over_a_system_family(machine):
    """EB Garamond ships inside TinyTeX and is invisible to fontconfig."""
    machine(packages=("ebgaramond",), system_fonts=("EB Garamond",))
    resolution = fonts.resolve("EB Garamond")
    assert resolution.via == "package"
    assert resolution.latex == r"\usepackage{ebgaramond}"


def test_a_system_family_is_used_when_no_package_provides_it(machine):
    machine(system_fonts=("Constantia",))
    resolution = fonts.resolve("Constantia")
    assert resolution.via == "system"
    assert resolution.latex == r"\setmainfont{Constantia}"


def test_an_unavailable_font_is_refused_rather_than_substituted(machine):
    """Refusing is the default: a substitution invalidates the author's spine."""
    machine(packages=("tgpagella",))
    with pytest.raises(fonts.FontUnavailable) as caught:
        fonts.resolve("Nonesuch Display")
    assert "--font-fallback" in str(caught.value)


def test_a_substitution_is_explained_in_the_authors_terms(machine):
    machine(packages=("tgpagella",))
    resolution = fonts.resolve("Nonesuch Display", allow_fallback=True)
    assert resolution.resolved == "Palatino"
    assert resolution.substituted
    assert "spine width" in resolution.note


def test_the_fallback_chain_is_walked_in_order(machine):
    """Latin Modern anchors it because every TeX installation has it."""
    machine(packages=("lmodern",))
    resolution = fonts.resolve("Nonesuch Display", allow_fallback=True)
    assert resolution.resolved == "Latin Modern Roman"


def test_an_incomplete_tex_installation_says_so(machine):
    machine(packages=())
    with pytest.raises(fonts.FontUnavailable) as caught:
        fonts.resolve("Nonesuch Display", allow_fallback=True)
    assert "tlmgr install lmodern" in str(caught.value)


def test_xelatex_gets_the_last_word_when_fontconfig_is_absent(monkeypatch):
    """A font fontconfig cannot see may still be one XeLaTeX can set."""
    monkeypatch.setattr(fonts, "_package_exists", lambda p: False)
    monkeypatch.setattr(fonts.shutil, "which",
                        lambda name: None if name == "fc-list" else "/usr/bin/" + name)
    resolution = fonts.resolve("Some Local Face")
    assert resolution.latex == r"\setmainfont{Some Local Face}"


@pytest.mark.parametrize("name,package", fonts.FALLBACKS)
def test_every_fallback_is_reachable(machine, name, package):
    """Each entry must be the answer when it is the only one installed.

    A fallback naming a package that is never consulted is a fallback that
    silently is not one, and the chain would be shorter than it reads.
    """
    machine(packages=(package,))
    assert fonts.resolve("Nonesuch Display", allow_fallback=True).resolved == name


def test_a_package_missing_the_font_files_it_loads_is_not_available(monkeypatch):
    """Debian ships ebgaramond.sty without EBGaramond-Initials; the package
    then looks installed and every build dies inside fontspec."""
    fonts._package_exists.cache_clear()
    monkeypatch.setattr(fonts.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(fonts, "_kpsewhich", lambda name: name == "ebgaramond.sty")
    try:
        assert not fonts._package_exists("ebgaramond")
    finally:
        fonts._package_exists.cache_clear()
