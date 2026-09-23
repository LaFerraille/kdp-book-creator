"""`kdp doctor`: what this machine can do, before it spends five minutes failing.

The thing to get right is that it must never fail itself. It is the command
someone runs precisely because their installation is incomplete, so every check
has to survive the absence of the thing it is checking for.
"""
import pytest

from kdp import doctor, fonts


@pytest.fixture
def machine(monkeypatch):
    """A described TeX installation, so the suite's own does not decide."""
    def setup(packages=(), hyphenation=("english",)):
        monkeypatch.setattr(fonts, "_package_exists", lambda p: p in packages)
        monkeypatch.setattr(fonts, "_system_font_exists", lambda f: False)
        monkeypatch.setattr(fonts, "_installed_hyphenation",
                            lambda: frozenset(hyphenation))
        monkeypatch.setattr(fonts.shutil, "which", lambda name: "/usr/bin/" + name)
    return setup


def test_a_machine_without_the_default_font_still_gets_a_report(machine):
    """It used to raise FontUnavailable and print nothing else.

    `resolve` refuses to substitute by default, which is right everywhere but
    here: doctor is asking a question, not building a book, and the answer to
    "is EB Garamond available?" is a line in the report, not an exception.
    """
    machine(packages=("lmodern",))
    findings = doctor._check_fonts()
    default = [f for f in findings if "EB Garamond" in f.name][0]
    assert not default.ok
    assert "Latin Modern Roman" in default.detail
    assert not default.blocking


def test_the_default_font_being_present_is_reported_as_such(machine):
    machine(packages=("ebgaramond",))
    default = [f for f in doctor._check_fonts() if "EB Garamond" in f.name][0]
    assert default.ok


def test_missing_hyphenation_is_listed_per_language_with_its_install_command(machine):
    """The failure is otherwise undetectable: polyglossia falls back silently."""
    machine(hyphenation=("english", "french"))
    finding = doctor._check_hyphenation()
    assert not finding.ok
    assert "English, French" in finding.detail
    assert "German" in finding.detail
    assert "tlmgr install hyphen-german" in finding.fix
    # Not blocking: a book in a language whose patterns are here is unaffected.
    assert not finding.blocking


def test_a_complete_installation_reports_no_missing_patterns(machine):
    from kdp import languages
    machine(hyphenation=[languages.hyphenation_name(c)
                         for c in languages.supported()])
    assert doctor._check_hyphenation().ok


def test_run_checks_everything_without_raising():
    """Whatever this machine has or lacks, the report is a report."""
    findings = doctor.run()
    assert findings
    assert all(isinstance(f.name, str) and f.detail for f in findings)


def test_a_blocking_failure_is_summarised_as_one():
    findings = [
        doctor.Finding("LaTeX engine", False, "none found", fix="brew install tectonic"),
        doctor.Finding("pandoc", False, "missing", blocking=False),
    ]
    text, can_build = doctor.report(findings)
    assert not can_build
    assert "1 problem(s) will stop a build: LaTeX engine" in text
    assert "brew install tectonic" in text


def test_an_optional_gap_does_not_stop_a_build():
    findings = [
        doctor.Finding("LaTeX engine", True, "xelatex"),
        doctor.Finding("pandoc", False, "missing", blocking=False),
    ]
    text, can_build = doctor.report(findings)
    assert can_build
    assert "Ready to build" in text


def test_everything_present_says_so():
    text, can_build = doctor.report([doctor.Finding("LaTeX engine", True, "xelatex")])
    assert can_build
    assert "Everything checks out." in text


def test_a_machine_with_no_font_at_all_gets_a_report_not_a_traceback(monkeypatch):
    """A bare CI runner had no font, not even Latin Modern, and doctor raised
    FontUnavailable instead of saying so: the one machine it exists for."""
    from kdp import doctor, fonts

    def no_font(*args, **kwargs):
        raise fonts.FontUnavailable("nothing resolves")

    monkeypatch.setattr(fonts, "resolve", no_font)
    monkeypatch.setattr(fonts, "available_fonts", dict)
    text, ok = doctor.report(doctor._check_fonts())
    assert not ok
    assert "no fallback font resolves" in text
