"""Everything the pipeline knows about a language, in one table.

The same six languages used to be described three times - stopwords for
detection in ingest, characters-per-word for the page estimate, and a
polyglossia name for typesetting. Adding a seventh meant finding all three,
and missing one produced a book that was detected correctly and then typeset
with the wrong hyphenation, which is the kind of bug nobody reports because it
only looks slightly wrong.

One row per language keeps those facts adjacent, so a language is either fully
supported or visibly absent.

`hyphenation` is the name TeX knows the pattern set by, which is not always the
ISO code or the polyglossia name - German's is "ngerman". It is here because a
missing pattern set is invisible: polyglossia falls back to English without
saying so, and a French book is then broken with English rules on every page.
"""

LANGUAGES = {
    "en": {
        "polyglossia": "english",
        "hyphenation": "english",
        "chars_per_word": 5.9,
        # Function words are the cheapest reliable detection signal and need no
        # dependency. Only words rare or absent in the other languages count.
        "stopwords": {"the", "and", "of", "to", "is", "it", "that", "with",
                      "from", "not", "on", "for", "was", "will", "come", "down"},
    },
    "fr": {
        "polyglossia": "french",
        "hyphenation": "french",
        "chars_per_word": 6.3,
        "stopwords": {"le", "la", "les", "des", "une", "est", "sur", "pas",
                      "qui", "dans", "avec", "pour", "que", "il", "elle",
                      "veut", "chaise", "et", "ne"},
    },
    "es": {
        "polyglossia": "spanish",
        "hyphenation": "spanish",
        "chars_per_word": 6.1,
        "stopwords": {"el", "los", "las", "una", "esta", "que", "por", "con",
                      "para", "no", "se", "quiere", "silla", "mesa", "gato",
                      "tiene", "bajar"},
    },
    "de": {
        "polyglossia": "german",
        "hyphenation": "ngerman",
        "chars_per_word": 6.8,
        "stopwords": {"der", "die", "das", "und", "ist", "nicht", "mit", "auf",
                      "den", "ein", "eine", "von", "zu", "sich"},
    },
    "it": {
        "polyglossia": "italian",
        "hyphenation": "italian",
        "chars_per_word": 6.2,
        "stopwords": {"il", "lo", "gli", "una", "che", "non", "per", "con",
                      "sono", "della", "sulla", "vuole"},
    },
    "pt": {
        "polyglossia": "portuguese",
        "hyphenation": "portuguese",
        "chars_per_word": 6.1,
        "stopwords": {"o", "os", "as", "uma", "que", "nao", "por", "com",
                      "para", "esta", "quer", "mesa"},
    },
}

DEFAULT_CHARS_PER_WORD = 6.0
DEFAULT_POLYGLOSSIA = "english"

STOPWORDS = {code: row["stopwords"] for code, row in LANGUAGES.items()}


def is_known(code):
    """Is this a language this project can typeset correctly?"""
    return (code or "en") in LANGUAGES


def polyglossia(code):
    """The polyglossia language name for an ISO code, for hyphenation."""
    row = LANGUAGES.get(code or "en")
    return row["polyglossia"] if row else DEFAULT_POLYGLOSSIA


def name(code):
    """The language's English name, for talking to a person."""
    row = LANGUAGES.get(code or "en")
    return row["polyglossia"].title() if row else str(code)


def hyphenation_name(code):
    """What TeX calls this language's hyphenation patterns, or None.

    None for a language not in the table above, and that distinction is the
    whole value of this function. Answering "english" for an unknown code -
    which is what this did - makes the caller's availability check pass for
    every language it cannot actually set, because English patterns are
    installed everywhere. The guard then covered exactly the six languages
    that were never going to be a problem and missed every one that was:
    Hungarian, Polish, Dutch and Turkish all built silently, in English.
    """
    row = LANGUAGES.get(code or "en")
    return row["hyphenation"] if row else None


def chars_per_word(code):
    """Average characters per word, including the trailing space."""
    row = LANGUAGES.get(code)
    return row["chars_per_word"] if row else DEFAULT_CHARS_PER_WORD


def supported():
    return sorted(LANGUAGES)
