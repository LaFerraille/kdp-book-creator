"""Render the Book IR to a reflowable EPUB 3 for Kindle.

Written natively rather than shelled out to pandoc. The IR is already
structured, so a converter would mean serialising it back to Markdown and
hoping the round trip preserves what discovery worked out - particularly the
language tagging on foreign phrases, which is exactly the sort of thing that
does not survive a Markdown round trip.

An ebook is reflowable: no trim size, no margins, no page count, no spine. The
reader chooses the type size, so the job here is clean semantic markup and
staying out of the way.
"""
import hashlib
import pathlib
import re
import zipfile
from xml.sax.saxutils import escape as xml_escape

from . import inline
from .ir import BlockQuote, Image, Lines, ListBlock, Paragraph, Rule

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

# Deliberately minimal. Readers and their users override nearly all of this,
# and a stylesheet that fights them makes a worse book, not a better one.
STYLESHEET = """@namespace epub "http://www.idpf.org/2007/ops";

body { margin: 0 5%; line-height: 1.5; text-align: justify; }
h1 { font-size: 1.6em; margin: 2em 0 0.2em; text-align: left; page-break-before: always; }
h2 { font-size: 1.15em; margin: 1.6em 0 0.4em; text-align: left; }
p { margin: 0; text-indent: 1.2em; }
/* The first paragraph after any heading or break is not indented. */
h1 + p, h2 + p, .subtitle + p, hr + p, blockquote + p { text-indent: 0; }
.subtitle { font-style: italic; margin: 0.2em 0 1.4em; text-align: left; color: #555; }
blockquote { margin: 1em 2em; font-style: italic; }
hr { border: 0; text-align: center; margin: 1.4em 0; }
hr::after { content: "* * *"; letter-spacing: 0.4em; }
img { max-width: 100%; height: auto; }
figcaption { font-size: 0.85em; text-align: center; color: #555; }
/* Line breaks the author chose. The hanging indent makes a line too long for
   a narrow screen read as a continuation rather than as a new line. */
p.verse { text-indent: 0; margin: 0.8em 0; padding-left: 1.5em;
          text-indent: -1.5em; }
"""

def inline_to_html(text, foreign_italics=False):
    """Convert inline Markdown to XHTML, escaping everything else.

    When italics mark foreign words rather than emphasis, they become
    ``<i class="foreign">`` instead of ``<em>``: <em> means stress, and a
    screen reader is entitled to pronounce it that way. Unlike the print path,
    links are kept live - an ebook can be tapped.
    """
    def emit(kind, value, match):
        value = xml_escape(value)
        if kind == "escaped":
            return value
        if kind == "bold":
            return f"<strong>{value}</strong>"
        if kind in ("italic", "bolditalic"):
            emphasised = (f'<i class="foreign">{value}</i>' if foreign_italics
                          else f"<em>{value}</em>")
            return f"<strong>{emphasised}</strong>" if kind == "bolditalic" else emphasised
        if kind == "code":
            return f"<code>{value}</code>"
        url = xml_escape(match.group("link_url"), {'"': "&quot;"})
        return f'<a href="{url}">{value}</a>'

    return inline.render(text, xml_escape, emit)


def _block_to_html(block, foreign):
    if isinstance(block, Paragraph):
        return f"<p>{inline_to_html(block.text, foreign)}</p>"
    if isinstance(block, BlockQuote):
        return f"<blockquote><p>{inline_to_html(block.text, foreign)}</p></blockquote>"
    if isinstance(block, ListBlock):
        tag = "ol" if block.ordered else "ul"
        items = "".join(f"<li>{inline_to_html(i, foreign)}</li>" for i in block.items)
        return f"<{tag}>{items}</{tag}>"
    if isinstance(block, Lines):
        body = "<br/>\n".join(inline_to_html(line, foreign) for line in block.lines)
        return f'<p class="verse">{body}</p>'
    if isinstance(block, Image):
        src = xml_escape(block.path, {'"': "&quot;"})
        alt = xml_escape(block.alt, {'"': "&quot;"})
        figure = f'<img src="{src}" alt="{alt}"/>'
        if block.alt:
            figure += f"<figcaption>{inline_to_html(block.alt, foreign)}</figcaption>"
        return f"<figure>{figure}</figure>"
    if isinstance(block, Rule):
        return "<hr/>"
    return ""


def chapter_xhtml(chapter, language, foreign=False):
    body = [f"<h1>{inline_to_html(chapter.title, foreign)}</h1>"]
    if chapter.subtitle:
        body.append(f'<p class="subtitle">{inline_to_html(chapter.subtitle, foreign)}</p>')
    body += [_block_to_html(b, foreign) for b in chapter.preamble]
    for section in chapter.sections:
        body.append(f"<h2>{inline_to_html(section.title, foreign)}</h2>")
        body += [_block_to_html(b, foreign) for b in section.blocks]

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{language}" lang="{language}">\n'
        f"<head><title>{xml_escape(chapter.title)}</title>"
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        "<body>\n" + "\n".join(b for b in body if b) + "\n</body>\n</html>\n"
    )


def _nav_xhtml(book, language):
    items = "\n".join(
        f'      <li><a href="chapter-{i:03d}.xhtml">'
        f"{xml_escape(c.title)}</a></li>"
        for i, c in enumerate(book.chapters, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{language}" lang="{language}">\n'
        "<head><title>Contents</title></head>\n<body>\n"
        '  <nav epub:type="toc" id="toc">\n    <h1>Contents</h1>\n    <ol>\n'
        f"{items}\n    </ol>\n  </nav>\n</body>\n</html>\n"
    )


def _content_opf(book, language, identifier, cover_image=None):
    meta = book.metadata
    manifest = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="style" href="style.css" media-type="text/css"/>',
    ]
    spine = []
    for i, _ in enumerate(book.chapters, 1):
        manifest.append(
            f'    <item id="ch{i:03d}" href="chapter-{i:03d}.xhtml" '
            f'media-type="application/xhtml+xml"/>'
        )
        spine.append(f'    <itemref idref="ch{i:03d}"/>')

    if cover_image:
        ext = pathlib.Path(cover_image).suffix.lower()
        media = "image/png" if ext == ".png" else "image/jpeg"
        manifest.append(
            f'    <item id="cover-image" href="cover{ext}" media-type="{media}" '
            f'properties="cover-image"/>'
        )

    optional = ""
    if meta.author:
        optional += f"    <dc:creator>{xml_escape(meta.author)}</dc:creator>\n"
    if meta.publisher:
        optional += f"    <dc:publisher>{xml_escape(meta.publisher)}</dc:publisher>\n"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="pub-id">{xml_escape(identifier)}</dc:identifier>\n'
        f"    <dc:title>{xml_escape(meta.title or 'Untitled')}</dc:title>\n"
        f"    <dc:language>{language}</dc:language>\n"
        f"{optional}"
        '    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n" + "\n".join(manifest) + "\n  </manifest>\n"
        '  <spine>\n' + "\n".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )


class EpubError(RuntimeError):
    """The book cannot be expressed as a valid EPUB."""


def render_epub(book, outpath, *, foreign_italics=False, identifier=None,
                cover_image=None):
    """Write a reflowable EPUB 3 and return its path.

    The archive layout is not free-form: `mimetype` must be the first entry and
    must be stored uncompressed, or readers reject the file.
    """
    outpath = pathlib.Path(outpath)
    outpath.parent.mkdir(parents=True, exist_ok=True)

    # EPUB 3 requires at least one spine item. Writing the file anyway produces
    # an archive with no content documents that readers and KDP both reject -
    # and, until this check existed, one that check_epub called valid.
    if not book.chapters:
        raise EpubError(
            "This book has no chapters, so the EPUB would contain no readable "
            "content and its spine would be empty. EPUB 3 requires at least "
            "one content document; KDP rejects files without one."
        )

    language = book.metadata.language or "en"
    # The print path takes some trouble to be byte-reproducible - a fixed
    # SOURCE_DATE_EPOCH, a stripped /ID - so that any diff in the output is a
    # real change. The EPUB quietly was not: zipfile stamps the current local
    # time into every entry, so two builds of an unchanged manuscript differed,
    # and a book built in another timezone differed again.
    # Python's hash() is salted per process, so using it here gave the same book
    # a different identifier on every build. The project goes to some trouble to
    # be byte-reproducible elsewhere; a stable digest keeps that promise.
    if not identifier:
        seed = (book.metadata.title or "book").encode("utf-8")
        identifier = f"urn:uuid:kdp-{hashlib.sha256(seed).hexdigest()[:16]}"

    with zipfile.ZipFile(outpath, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype first and stored, which the EPUB specification requires.
        z.writestr(_entry("mimetype", zipfile.ZIP_STORED),
                   "application/epub+zip")
        z.writestr(_entry("META-INF/container.xml"), CONTAINER_XML)
        z.writestr(_entry("OEBPS/style.css"), STYLESHEET)
        z.writestr(_entry("OEBPS/nav.xhtml"), _nav_xhtml(book, language))
        z.writestr(_entry("OEBPS/content.opf"),
                   _content_opf(book, language, identifier, cover_image))
        for i, chapter in enumerate(book.chapters, 1):
            z.writestr(_entry(f"OEBPS/chapter-{i:03d}.xhtml"),
                       chapter_xhtml(chapter, language, foreign_italics))
        if cover_image:
            src = pathlib.Path(cover_image)
            z.writestr(_entry(f"OEBPS/cover{src.suffix.lower()}"),
                       src.read_bytes())

    return outpath


# --- validation ----------------------------------------------------------
def _entry(name, compress_type=zipfile.ZIP_DEFLATED):
    """One archive member, timestamped with the epoch zip files count from.

    1980-01-01 is the earliest a zip can record, and any fixed value would do;
    what matters is that it is fixed. `writestr` with a bare name uses the
    current local time instead.
    """
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compress_type
    # External attributes are also part of the bytes, and zipfile derives them
    # from the process umask for a file read off disk.
    info.external_attr = 0o644 << 16
    return info


def check_epub(path):
    """Structural checks that do not need epubcheck installed.

    Not a substitute for epubcheck, but it catches the mistakes that actually
    happen when writing an EPUB by hand, and it runs everywhere.
    """
    path = pathlib.Path(path)
    problems = []
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"not a readable EPUB archive: {exc}"]
    with archive as z:
        names = z.namelist()
        if not names or names[0] != "mimetype":
            problems.append("mimetype must be the first entry in the archive")
        else:
            info = z.getinfo("mimetype")
            if info.compress_type != zipfile.ZIP_STORED:
                problems.append("mimetype must be stored uncompressed")
            if z.read("mimetype") != b"application/epub+zip":
                problems.append("mimetype content is wrong")

        for required in ("META-INF/container.xml", "OEBPS/content.opf", "OEBPS/nav.xhtml"):
            if required not in names:
                problems.append(f"missing {required}")

        if "OEBPS/content.opf" in names:
            opf = z.read("OEBPS/content.opf").decode("utf-8")
            for href in re.findall(r'href="([^"]+)"', opf):
                if not href.startswith(("http:", "https:")) and f"OEBPS/{href}" not in names:
                    problems.append(f"content.opf lists {href}, which is not in the archive")
            if "<dc:language>" not in opf:
                problems.append("content.opf declares no language")
            # An empty spine is the failure that looks most like success: the
            # archive is well-formed, every required file is present, and there
            # is nothing to read. EPUB 3 requires at least one itemref.
            spine = re.search(r"<spine[^>]*>(.*?)</spine>", opf, re.S)
            if spine is None:
                problems.append("content.opf has no spine")
            elif not re.search(r"<itemref\b", spine.group(1)):
                problems.append(
                    "the spine is empty, so the book has no readable content"
                )

        # Every XHTML document must actually parse.
        from xml.etree import ElementTree
        for name in names:
            if name.endswith(".xhtml"):
                try:
                    ElementTree.fromstring(z.read(name))
                except ElementTree.ParseError as exc:
                    problems.append(f"{name} is not well-formed XML: {exc}")

    return problems
