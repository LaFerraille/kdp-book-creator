"""One tokenizer for inline Markdown, shared by every output format.

The print and ebook renderers need the same spans - bold, italic, code, links -
and differ only in what they emit for each. Keeping one regex and one walk here
means a fix to what counts as emphasis lands in the PDF and the EPUB at the same
time. When this pattern lived in both modules it was byte-identical in each,
which is exactly the arrangement that drifts the first time someone edits one.
"""
import re

# Bold before italic so `**x**` is not read as an empty italic pair. Emphasis
# markers must hug their content (no space after the opening marker), which is
# what stops "2 * 3 = 6" being read as markup.
PATTERN = re.compile(
    # A backslash escape comes first so it wins: "\*" is a literal asterisk,
    # and printing the backslash - which is what happened before - puts a
    # stray mark in the middle of a sentence in a finished book.
    r"\\(?P<escaped>[\\`*_{}\[\]()#+\-.!])"
    # Three markers before two, or `***x***` is read as bold followed by a
    # stray `*x*`, and the asterisks are printed. A Word run carrying both
    # bold and italic is the common way in: it converts to `***x***`, which
    # nothing here could parse, so the marks reached the page.
    r"|\*\*\*(?P<bolditalic>\S(?:[^*]*\S)?)\*\*\*"
    r"|\*\*(?P<bold>\S(?:[^*]*\S)?)\*\*"
    r"|\*(?P<italic>\S(?:[^*\n]*\S)?)\*"
    r"|`(?P<code>[^`\n]+)`"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)]*)\)"
)

KINDS = ("escaped", "bolditalic", "bold", "italic", "code")


def render(text, escape, emit):
    """Walk `text`, escaping plain runs and handing each span to `emit`.

    `emit(kind, value, match)` returns the markup for one span, where `kind` is
    "escaped" (a character the author wanted printed literally), "bolditalic",
    "bold", "italic", "code" or "link". It receives the raw value and the match,
    so a format that needs more than the span's text - a link's URL - can reach
    for it without this function knowing which formats care.
    """
    out, cursor = [], 0
    for match in PATTERN.finditer(text):
        out.append(escape(text[cursor:match.start()]))
        for kind in KINDS:
            value = match.group(kind)
            if value is not None:
                out.append(emit(kind, value, match))
                break
        else:
            out.append(emit("link", match.group("link_text"), match))
        cursor = match.end()
    out.append(escape(text[cursor:]))
    return "".join(out)
