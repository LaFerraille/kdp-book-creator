"""Build a .docx from a Markdown fixture, so the Word path has a real input.

The DOCX reader is the one input path that cannot be exercised by a text file
in the repository: what it parses is WordprocessingML, and the bugs that live
there - a heading style spelled a way we do not match, a run carrying both
bold and italic - only appear when the input is genuinely a Word document.

Checking a binary in would be the obvious answer and the wrong one: it cannot
be reviewed in a diff, and it drifts silently away from the Markdown it is
supposed to be the same book as. Generating it from that Markdown instead makes
the equivalence the tests assert a property of the fixture rather than a claim
about it, and keeps the fixture reviewable.

This writes the parts a real Word file has, not only the two our reader opens,
so the result also opens in Word - a fixture our own reader accepts and Word
would not is a fixture that proves nothing.
"""
import re
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n", re.S)

# Bold-italic first, so `***x***` is not read as bold followed by a stray pair.
_SPANS = re.compile(r"\*\*\*(?P<both>[^*]+)\*\*\*"
                    r"|\*\*(?P<bold>[^*]+)\*\*"
                    r"|\*(?P<italic>[^*\n]+)\*")


def _xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _runs(text):
    """Markdown emphasis as Word runs, which is where it lives in a .docx.

    A backslash-escaped asterisk is literal text in the Markdown and literal
    text in Word too, so the escape is dropped rather than carried across: Word
    has no such convention, and a real export would show the character.
    """
    out, cursor = [], 0
    for match in _SPANS.finditer(text):
        if cursor < match.start():
            out.append((text[cursor:match.start()], False, False))
        if match.group("both") is not None:
            out.append((match.group("both"), True, True))
        elif match.group("bold") is not None:
            out.append((match.group("bold"), True, False))
        else:
            out.append((match.group("italic"), False, True))
        cursor = match.end()
    out.append((text[cursor:], False, False))

    runs = []
    for body, bold, italic in out:
        body = body.replace("\\*", "*").replace("\\\\", "\\")
        if body:
            runs.append((body, bold, italic))
    return runs


def _paragraph(text, style=None, numbered=False):
    props = []
    if style:
        props.append(f'<w:pStyle w:val="{style}"/>')
    if numbered:
        props.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    out = ["<w:p>"]
    if props:
        out.append("<w:pPr>" + "".join(props) + "</w:pPr>")
    for body, bold, italic in _runs(text):
        marks = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "")
        out.append("<w:r>"
                   + (f"<w:rPr>{marks}</w:rPr>" if marks else "")
                   + f'<w:t xml:space="preserve">{_xml_escape(body)}</w:t>'
                   "</w:r>")
    out.append("</w:p>")
    return "".join(out)


def document_xml(markdown):
    """The body of the .docx: headings as Heading<n>, emphasis as run properties."""
    matter = _FRONT_MATTER.match(markdown)
    if matter:
        markdown = markdown[matter.end():]

    body, wrapped = [], []

    def flush():
        # Word has no notion of a wrapped line: a paragraph is one <w:p>
        # however many lines the Markdown spread it over. Emitting one
        # paragraph per source line would make the .docx a different book from
        # the .md, which is the one thing this fixture must not be.
        if wrapped:
            body.append(_paragraph(" ".join(wrapped)))
            wrapped.clear()

    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            body.append(_paragraph(heading.group(2),
                                   style=f"Heading{len(heading.group(1))}"))
            continue
        bullet = _BULLET.match(stripped)
        if bullet:
            flush()
            body.append(_paragraph(bullet.group(1), numbered=True))
            continue
        wrapped.append(stripped)
    flush()

    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>')


def core_xml(title=None, author=None, language=None):
    fields = ""
    if title:
        fields += f"<dc:title>{_xml_escape(title)}</dc:title>"
    if author:
        fields += f"<dc:creator>{_xml_escape(author)}</dc:creator>"
    if language:
        fields += f"<dc:language>{_xml_escape(language)}</dc:language>"
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'{fields}</cp:coreProperties>')


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd'
    '.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd'
    '.openxmlformats-package.core-properties+xml"/>'
    '</Types>'
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
    'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '</Relationships>'
)


def write_docx(path, markdown, title=None, author=None, language=None):
    """Write `markdown` to `path` as a Word document. Returns the path.

    A fixed timestamp on every entry, so building the same fixture twice gives
    the same bytes - the property the rest of this project takes trouble to
    keep, and no reason to break here.
    """
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _RELS,
        "word/document.xml": document_xml(markdown),
        "docProps/core.xml": core_xml(title, author, language),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text.encode("utf-8"))
    return path
