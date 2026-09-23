"""Read a .docx manuscript without needing pandoc.

DOCX is the format most authors actually hand you, so making it depend on an
external binary means the common case fails on a machine that is otherwise
perfectly capable. The file is a zip of XML and the part we need - headings,
emphasis, lists - is small and stable, so we read it directly.

The output is Markdown rather than the Book IR, because every other input
format already converges on the Markdown parser. One structural parser is
easier to reason about and to test than one per format, and it means a heading
found here behaves exactly like a heading typed by hand.
"""
import pathlib
import re
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxError(RuntimeError):
    pass


def _style_of(paragraph):
    props = paragraph.find(W + "pPr")
    if props is None:
        return None
    style = props.find(W + "pStyle")
    return style.get(W + "val") if style is not None else None


def _heading_level(style):
    """Word's heading styles, in the several spellings producers use.

    Word writes "Heading1"; LibreOffice writes "Heading1" too but localised
    templates produce "berschrift1" and Google Docs exports "Heading1" with a
    leading capital only. Matching on the trailing digit covers all of them
    without a table of every locale.
    """
    if not style:
        return None
    match = re.match(r"^(?:heading|berschrift|titre|ttulo|titolo)\s*(\d)$",
                     re.sub(r"[^A-Za-z0-9]", "", style).lower())
    return int(match.group(1)) if match else None


def _is_list(paragraph):
    props = paragraph.find(W + "pPr")
    return props is not None and props.find(W + "numPr") is not None


def _run_text(run):
    """Text of one run, with tabs and breaks preserved as spaces."""
    out = []
    for node in run:
        tag = node.tag
        if tag == W + "t":
            out.append(node.text or "")
        elif tag in (W + "tab", W + "br"):
            out.append(" ")
    return "".join(out)


def _escape(text):
    """Neutralise Markdown metacharacters that came from prose, not markup.

    Link and code syntax is escaped, because a bracket in Word is a bracket.
    Emphasis markers deliberately are not: a .docx carrying "**3 000 pages**" as
    literal characters was exported from Markdown by something that did not
    map emphasis, and every such file in practice means the emphasis. Printing
    the asterisks instead is never what anyone wanted, and it would make the
    same book set differently depending on which file you were handed.
    """
    return re.sub(r"([`\[\]])", r"\\\1", text)


def _paragraph_markdown(paragraph):
    """One <w:p> as Markdown, carrying bold/italic runs across."""
    pieces = []
    for run in paragraph.iter(W + "r"):
        text = _run_text(run)
        if not text:
            continue
        props = run.find(W + "rPr")
        bold = italic = False
        if props is not None:
            # <w:b/> means on; <w:b w:val="0"/> means explicitly off.
            for node, flag in ((props.find(W + "b"), "b"), (props.find(W + "i"), "i")):
                if node is None:
                    continue
                on = node.get(W + "val") not in ("0", "false")
                if flag == "b":
                    bold = on
                else:
                    italic = on
        body = _escape(text)
        # Emphasis markers must hug the words or Markdown ignores them, so the
        # surrounding spaces are lifted out of the marked span.
        if (bold or italic) and body.strip():
            lead = body[:len(body) - len(body.lstrip())]
            tail = body[len(body.rstrip()):]
            core = body.strip()
            if bold:
                core = f"**{core}**"
            if italic:
                core = f"*{core}*"
            body = f"{lead}{core}{tail}"
        pieces.append(body)
    return "".join(pieces).strip()


# Word writes these when nobody filled the field in. Treating them as a title
# would put "Un-named" on a cover.
_PLACEHOLDERS = {"", "un-named", "unnamed", "untitled", "normal.dotm",
                 "document", "microsoft word"}

DC = "{http://purl.org/dc/elements/1.1/}"


def metadata_from(path):
    """Title and author as recorded in the .docx properties, if real.

    Word stores these in docProps/core.xml, which is where a title belongs and
    the only place in a .docx that can be said to hold one - the body has
    headings, and a heading is a chapter.
    """
    out = {}
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return out
    with archive:
        if "docProps/core.xml" not in archive.namelist():
            return out
        try:
            from lxml import etree
            root = etree.fromstring(archive.read("docProps/core.xml"))
        except Exception:
            return out

    for tag, field in ((DC + "title", "title"), (DC + "creator", "author"),
                       (DC + "language", "language")):
        node = root.find(tag)
        value = (node.text or "").strip() if node is not None else ""
        if value and value.lower() not in _PLACEHOLDERS:
            out[field] = value
    return out


def to_markdown(path):
    """Convert a .docx file to Markdown."""
    path = pathlib.Path(path)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise DocxError(
            f"{path.name} is not a readable .docx file ({exc}). If it was "
            f"renamed from .doc, open it in Word and save it as .docx."
        ) from exc

    with archive:
        if "word/document.xml" not in archive.namelist():
            raise DocxError(
                f"{path.name} is a zip file but not a Word document - it has no "
                f"word/document.xml."
            )
        try:
            from lxml import etree
        except ImportError as exc:  # pragma: no cover - declared dependency
            raise DocxError("Reading .docx needs lxml. "
                            "Run: uv pip install -r requirements.txt") from exc
        root = etree.fromstring(archive.read("word/document.xml"))

    lines = []
    for paragraph in root.iter(W + "p"):
        text = _paragraph_markdown(paragraph)
        style = _style_of(paragraph)
        level = _heading_level(style)

        if level:
            # Word allows an empty heading; emitting it would open a chapter
            # with no title and swallow the text that follows.
            if text:
                lines += ["", "#" * min(level, 6) + " " + text, ""]
            continue
        if not text:
            lines.append("")
            continue
        if _is_list(paragraph):
            lines.append(f"- {text}")
            continue
        lines += [text, ""]

    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
