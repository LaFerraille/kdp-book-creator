"""Turn manuscript text into LaTeX safely.

Two jobs, and the order between them is the whole difficulty: markup has to be
recognised *before* escaping (or `\\textit` would itself be escaped), while the
text inside that markup still has to be escaped afterwards. Doing it in one pass
over alternating segments is what keeps both true.

Escaping failures here are silent rather than loud. An unescaped `$` does not
break the build; it opens math mode and quietly reflows the rest of the
paragraph. That is why this module is small, pure and heavily tested.
"""
import re

from . import inline

_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# One pass over the whole string. Replacing character by character cannot work:
# the replacement for `\` itself contains braces, so a later brace rule would
# escape them again and emit \textbackslash\{\}.
_SPECIAL = re.compile("|".join(re.escape(c) for c in _ESCAPES))


def escape(text):
    """Escape LaTeX's special characters, leaving Unicode alone.

    XeLaTeX reads UTF-8 natively, so accented letters, guillemets, dashes and
    currency signs need no treatment and must pass through unchanged.
    """
    return _SPECIAL.sub(lambda m: _ESCAPES[m.group()], text)


_WRAPPERS = {
    "bold": r"\textbf{%s}",
    "italic": r"\textit{%s}",
    "code": r"\texttt{%s}",
}


def inline_to_latex(text, italic_command="textit"):
    """Convert inline Markdown to LaTeX, escaping everything else.

    Links are flattened to their text: a printed book cannot be clicked, and a
    bare URL in the middle of a paragraph is worse than none. The EPUB renderer
    keeps them live.

    ``italic_command`` lets a book whose italics mark foreign words use a
    wrapper that also suppresses hyphenation, rather than plain \textit.
    """
    italic_wrapper = "\\" + italic_command + "{%s}"
    wrappers = dict(_WRAPPERS, italic=italic_wrapper,
                    # Bold wrapping italic, so a foreign-word italic keeps its
                    # suppressed hyphenation when it is also bold.
                    bolditalic=r"\textbf{%s}" % italic_wrapper)

    def emit(kind, value, _match):
        # An escaped character and a link's text are both just text; the
        # wrapper lookup covers the rest.
        return wrappers[kind] % escape(value) if kind in wrappers else escape(value)

    return inline.render(text, escape, emit)
