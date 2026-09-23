"""One row per language, and what each field promises.

This table is the single place three separate questions are answered - how to
detect a language, how wide its words are, and what TeX calls its hyphenation
patterns. It had no test, and the bug that cost most was in the third: an
unknown code was answered "english", so every caller that asked "can I
hyphenate this?" got yes for every language this project cannot set.
"""
import pytest

from kdp import languages

UNKNOWN = ("hu", "pl", "nl", "tr", "zz", "", "not-a-code")


@pytest.mark.parametrize("code", sorted(languages.LANGUAGES))
def test_every_language_is_completely_described(code):
    """A language is either fully supported or visibly absent - never half."""
    row = languages.LANGUAGES[code]
    assert set(row) == {"polyglossia", "hyphenation", "chars_per_word", "stopwords"}
    assert row["polyglossia"] and row["hyphenation"]
    assert 4.0 < row["chars_per_word"] < 9.0
    assert len(row["stopwords"]) >= 10


@pytest.mark.parametrize("code", UNKNOWN[:-2])     # "" and a bare code below
def test_an_unknown_language_has_no_hyphenation_name(code):
    """The failure this guards: a name of "english" for a language we cannot set.

    English patterns are installed on every TeX system, so answering "english"
    made `hyphenation_available` return True for Hungarian, Polish, Dutch and
    Turkish alike. The book then built silently with English rules.
    """
    assert languages.hyphenation_name(code) is None
    assert not languages.is_known(code)


@pytest.mark.parametrize("code", sorted(languages.LANGUAGES))
def test_a_supported_language_names_its_patterns(code):
    assert isinstance(languages.hyphenation_name(code), str)
    assert languages.is_known(code)


def test_german_patterns_are_not_named_after_the_iso_code():
    """The reason this field exists at all: 'de' is spelt 'ngerman' to TeX."""
    assert languages.hyphenation_name("de") == "ngerman"
    assert languages.polyglossia("de") == "german"


def test_no_language_means_english():
    """None is the caller saying "not stated", which for a default is English."""
    assert languages.hyphenation_name(None) == "english"
    assert languages.polyglossia(None) == "english"
    assert languages.is_known(None)


def test_an_unknown_language_still_gets_an_estimate_width():
    """The page estimate must degrade, not fail - it is only ever approximate."""
    assert languages.chars_per_word("zz") == languages.DEFAULT_CHARS_PER_WORD
    assert languages.chars_per_word("fr") == languages.LANGUAGES["fr"]["chars_per_word"]


def test_supported_is_sorted_and_complete():
    assert languages.supported() == sorted(languages.LANGUAGES)
