"""Inspect finished files against KDP's requirements, before anyone uploads them.

This is the module that earns the project its trust. Everything else produces a
PDF; this one is willing to say the PDF is wrong. It reads the *output*, never
the inputs or the intentions that produced it - a renderer bug that quietly
drops font embedding is invisible to a test of the renderer's source and
obvious here.

Checks are graded. An **error** is something KDP rejects or prints wrongly. A
**warning** is something that usually indicates a mistake but can be deliberate.
An **info** is context worth having in the report.
"""
import pathlib
import re
from dataclasses import dataclass, field

import pikepdf

from . import specs
from .geometry import interior_page_size

ERROR, WARNING, INFO = "error", "warning", "info"

# KDP rejects file names carrying emoji or other unsupported characters.
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9 ._()-]+$")


@dataclass
class Check:
    name: str
    passed: bool
    severity: str
    detail: str
    fix: str = ""

    @property
    def icon(self):
        if self.passed:
            return "PASS"
        return {ERROR: "FAIL", WARNING: "WARN", INFO: "INFO"}[self.severity]


@dataclass
class PreflightReport:
    target: str = ""
    checks: list = field(default_factory=list)

    def add(self, name, passed, severity, detail, fix=""):
        self.checks.append(Check(name, passed, severity, detail, fix))
        return self.checks[-1]

    @property
    def errors(self):
        return [c for c in self.checks if not c.passed and c.severity == ERROR]

    @property
    def warnings(self):
        return [c for c in self.checks if not c.passed and c.severity == WARNING]

    @property
    def ok(self):
        """Ready to upload: no errors. Warnings are for a human to weigh."""
        return not self.errors

    def to_markdown(self):
        lines = [f"# Preflight — {self.target}", ""]
        verdict = "Ready to upload" if self.ok else f"{len(self.errors)} problem(s) to fix"
        lines += [f"**{verdict}**", ""]
        for check in self.checks:
            lines.append(f"- `{check.icon}` **{check.name}** — {check.detail}")
            if not check.passed and check.fix:
                lines.append(f"    - _Fix:_ {check.fix}")
        return "\n".join(lines) + "\n"

    def summary(self):
        passed = sum(1 for c in self.checks if c.passed)
        return (f"{passed}/{len(self.checks)} checks passed, "
                f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)")


# --- individual checks ---------------------------------------------------
def _check_filename(report, path):
    stem = path.name
    report.add(
        "File name", bool(SAFE_FILENAME.match(stem)), ERROR,
        f"{stem!r}",
        "KDP rejects file names containing emoji or unsupported characters. "
        "Use letters, digits, spaces, dots, hyphens and underscores only.",
    )


def _check_size(report, path):
    limit = specs.constants()["file"]["max_size_mb"]
    mb = path.stat().st_size / 1_000_000
    report.add(
        "File size", mb <= limit, ERROR,
        f"{mb:.1f} MB (limit {limit} MB)",
        "Reduce image resolution or optimise the PDF.",
    )


def _check_encryption(report, pdf):
    report.add(
        "Not encrypted", not pdf.is_encrypted, ERROR,
        "encrypted" if pdf.is_encrypted else "no password or permissions set",
        "Remove password protection; KDP cannot open locked files.",
    )


def _check_page_size(report, pdf, spec):
    """Every page must match the trim size, or the bleed size when bleeding."""
    expected = interior_page_size(spec.trim_w, spec.trim_h, bleed=spec.bleed)
    want = (round(expected.width * 72, 1), round(expected.height * 72, 1))

    sizes = set()
    for page in pdf.pages:
        box = [float(v) for v in page.MediaBox]
        sizes.add((round(box[2] - box[0], 1), round(box[3] - box[1], 1)))

    uniform = len(sizes) == 1
    report.add(
        "Uniform page size", uniform, ERROR,
        f"{len(sizes)} distinct page size(s)" if not uniform else "all pages identical",
        "Mixed page sizes are rejected. Check for an imported page at another size.",
    )
    if not uniform:
        return

    got = sizes.pop()
    matches = abs(got[0] - want[0]) < 1.0 and abs(got[1] - want[1]) < 1.0
    report.add(
        "Page size matches trim", matches, ERROR,
        f'{got[0]/72:.3f}" x {got[1]/72:.3f}" '
        f'(expected {want[0]/72:.3f}" x {want[1]/72:.3f}")',
        "The PDF page size must equal the trim size, or trim plus bleed for a "
        "bleeding book.",
    )


def _font_descriptors(page):
    fonts = page.get("/Resources", {}).get("/Font", {}) or {}
    for font in fonts.values():
        descriptor = font.get("/FontDescriptor")
        if descriptor is None and font.get("/DescendantFonts"):
            descriptor = font["/DescendantFonts"][0].get("/FontDescriptor")
        yield font, descriptor


def _check_fonts(report, pdf):
    missing = set()
    total = 0
    for page in pdf.pages:
        for font, descriptor in _font_descriptors(page):
            total += 1
            embedded = descriptor is not None and any(
                key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
            )
            if not embedded:
                missing.add(str(font.get("/BaseFont", "<unnamed>")))

    report.add(
        "Fonts embedded", not missing, ERROR,
        f"{total} font reference(s), all embedded" if not missing
        else f"not embedded: {sorted(missing)}",
        "Every font must be embedded, or KDP substitutes one and your line "
        "breaks - and therefore your page count and spine width - change.",
    )


def _check_annotations(report, pdf):
    """Annotations, links and form fields are all rejected."""
    count = sum(len(page.get("/Annots", []) or []) for page in pdf.pages)
    report.add(
        "No annotations", count == 0, ERROR,
        "none" if count == 0 else f"{count} annotation(s)",
        "Remove comments, links and form fields before uploading.",
    )


def _check_outlines(report, pdf):
    has = "/Outlines" in pdf.Root and bool(pdf.Root.get("/Outlines", {}).get("/First"))
    report.add(
        "No bookmarks", not has, ERROR,
        "none" if not has else "document outline present",
        "KDP asks that print files carry no bookmarks.",
    )


def _check_metadata(report, pdf):
    info = dict(pdf.docinfo) if pdf.docinfo else {}
    report.add(
        "No document metadata", not info, WARNING,
        "clean" if not info else f"{sorted(str(k) for k in info)}",
        "Producer and creation-date fields are best cleared for submission.",
    )


def _check_images(report, pdf):
    """Every raster image must resolve to at least 300 DPI once placed.

    Effective DPI, not stored DPI: an image's real resolution on the page is
    its pixel count divided by the width it is drawn at, so the same file can
    be fine small and unacceptable full-bleed.
    """
    minimum = specs.constants()["file"]["min_image_dpi"]
    worst = None
    count = 0

    for page in pdf.pages:
        resources = page.get("/Resources", {})
        for name, image in (resources.get("/XObject", {}) or {}).items():
            if image.get("/Subtype") != "/Image":
                continue
            count += 1
            px_w = int(image.get("/Width", 0))
            box = [float(v) for v in page.MediaBox]
            page_w_in = (box[2] - box[0]) / 72
            # Without parsing the content stream we cannot know the exact drawn
            # width, so assume full page width: the most generous reading, which
            # makes this check conservative rather than alarmist.
            dpi = px_w / page_w_in if page_w_in else 0
            if worst is None or dpi < worst[1]:
                worst = (str(name), dpi)

    if count == 0:
        report.add("Image resolution", True, INFO, "no raster images")
        return
    report.add(
        "Image resolution", worst[1] >= minimum, WARNING,
        f"{count} image(s), lowest about {worst[1]:.0f} DPI at full page width",
        f"KDP wants at least {minimum} DPI. Re-export the image larger, or place "
        f"it smaller on the page.",
    )


def _check_page_count(report, pdf, spec):
    pages = len(pdf.pages)
    limits = spec.page_limits()
    if limits is None:
        report.add("Page count", False, ERROR, f"{pages} pages",
                   "This trim size and paper combination is not offered by KDP.")
        return
    within = limits["min"] <= pages <= limits["max"]
    report.add(
        "Page count in range", within, ERROR,
        f"{pages} pages (KDP allows {limits['min']}-{limits['max']} "
        f"at {spec.trim_w}x{spec.trim_h} on {spec.paper})",
        "Add or remove pages, or choose a different trim size or paper.",
    )


def _page_content(page):
    """The page's content stream bytes.

    /Contents is either a single stream or an *array* of them, and calling
    read_bytes() on the array raises. Catching that broadly is how this check
    came to report every page of a full book as blank, so the array case is
    handled explicitly and anything else is left to fail loudly.
    """
    if "/Contents" not in page:
        return b""
    contents = page["/Contents"]
    if isinstance(contents, pikepdf.Array):
        return b"\n".join(bytes(s.read_bytes()) for s in contents)
    return bytes(contents.read_bytes())


# Text-showing operators. Counting these beats measuring stream length: a page
# holding only a folio still has a content stream of respectable size.
_TEXT_OPS = re.compile(rb"(?:^|[\s\]>)])(?:Tj|TJ|'|\")")


def _check_blank_pages(report, pdf):
    """Excessive blank pages are one of KDP's listed causes of rejection."""
    blank = 0
    for page in pdf.pages:
        # A page carrying nothing but a page number is blank to a reader.
        if len(_TEXT_OPS.findall(_page_content(page))) <= 2:
            blank += 1
    share = blank / max(1, len(pdf.pages))
    report.add(
        "Blank pages", share < 0.10, WARNING,
        f"{blank} of {len(pdf.pages)} pages appear blank ({share:.0%})",
        "KDP lists excessive blank pages as a cause of rejection. Some are "
        "normal where chapters open on a right-hand page.",
    )


def _check_transparency(report, pdf):
    groups = sum(
        1 for page in pdf.pages
        if "/Group" in page and page["/Group"].get("/S") == "/Transparency"
    )
    report.add(
        "Transparency flattened", groups == 0, WARNING,
        "no transparency groups" if groups == 0 else f"{groups} page(s) with a transparency group",
        "KDP asks for flattened transparency; unflattened art can print with "
        "unexpected edges.",
    )


# --- entry point ---------------------------------------------------------
# An overfull box this wide is ink in the margin that a reader will see. Below
# it, TeX is reporting a hair's overshoot that no one can detect on paper.
VISIBLE_OVERFULL_PT = 12.0
ANY_OVERFULL_PT = 2.0


def _check_overfull(report, overfull):
    """Text that ran past the text block.

    Nothing else here can catch this. Every geometric check passes on a page
    whose text spills into the margin: the page is the right size, the trim is
    right, the fonts are embedded. Only the typesetter knows, and it says so in
    the log.

    Which is why `overfull=None` - a PDF someone else made, handed to
    `kdp check` - has to say so rather than pass. An empty tuple means "the
    typesetter was asked and found none"; None means "there was no typesetter
    to ask". Reporting the second as the first printed "PASS Text inside the
    margins" over a file nothing had ever measured, on exactly the files most
    likely to have text in the margin.
    """
    if overfull is None:
        report.add(
            "Text inside the margins", False, INFO,
            "not checked - this needs the typesetter's log, and this PDF was "
            "not built here",
            "Build the interior with `kdp build` to have this measured, or "
            "open the PDF and look at the outer edge of a few full pages.",
        )
        return

    bad = [w for w in overfull if w >= ANY_OVERFULL_PT]
    visible = [w for w in bad if w >= VISIBLE_OVERFULL_PT]
    worst = max(bad) if bad else 0.0
    report.add(
        "Text inside the margins", not visible,
        ERROR if visible else WARNING,
        "no text runs past the text block" if not bad
        else f"{len(bad)} line(s) run past the text block, worst by "
             f"{worst:.1f}pt ({worst / 72:.2f}in)",
        "Usually a word the typesetter could not break: a URL, or a language "
        "whose hyphenation patterns are not installed. Check `kdp doctor`.",
    )


def preflight_interior(pdf_path, spec, overfull=None):
    """Run every interior check and return the report."""
    pdf_path = pathlib.Path(pdf_path)
    report = PreflightReport(target=pdf_path.name)

    _check_filename(report, pdf_path)
    _check_size(report, pdf_path)

    with pikepdf.open(pdf_path) as pdf:
        _check_encryption(report, pdf)
        _check_page_size(report, pdf, spec)
        _check_page_count(report, pdf, spec)
        _check_fonts(report, pdf)
        _check_annotations(report, pdf)
        _check_outlines(report, pdf)
        _check_metadata(report, pdf)
        _check_images(report, pdf)
        _check_blank_pages(report, pdf)
        _check_transparency(report, pdf)

    _check_overfull(report, overfull)
    return report


def _check_cover_has_content(report, pdf):
    """A cover with nothing on it.

    When a manuscript carries no title, the cover used to render as a coloured
    rectangle and pass every other check - right size, right bleed, fonts
    embedded, ten out of ten - because none of them ask whether anything is
    printed on it.
    """
    page = pdf.pages[0]
    text_ops = len(_TEXT_OPS.findall(_page_content(page)))
    resources = page.get("/Resources", {})
    images = len(resources.get("/XObject", {}) or {})
    report.add(
        "Cover has content", bool(text_ops or images), ERROR,
        f"{text_ops} text operation(s), {images} image(s)" if (text_ops or images)
        else "nothing is printed on this cover - it is a blank rectangle",
        "A cover needs at least a title. Pass --title, or put one in the "
        "manuscript's front matter.",
    )


PT_PER_INCH = 72.0

# Operators that put glyphs on the page. The text matrix at the moment one of
# these runs is where those glyphs start.
_SHOWS_TEXT = {"Tj", "TJ", "'", '"'}


def _multiply(m, n):
    """The product of two PDF transforms, each given as (a, b, c, d, e, f)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _ink(page):
    """Where this page puts text and images, in points from the bottom-left.

    Returns (text_points, image_boxes), or None when the content stream cannot
    be read - which callers must report as "not checked" rather than as a pass.

    Only text origins and image extents are collected. A background fill is
    deliberately not ink for this purpose: KDP prints its barcode over whatever
    colour is there, and a cover that is coloured to its edges is the normal
    case, not a fault.
    """
    try:
        instructions = pikepdf.parse_content_stream(page)
    except Exception:
        return None

    stack, ctm = [], _IDENTITY
    text_matrix = line_matrix = _IDENTITY
    leading = 0.0
    xobjects = page.get("/Resources", {}).get("/XObject", {}) or {}
    text_points, image_boxes = [], []

    def numbers(operands):
        return [float(v) for v in operands]

    for operands, operator in instructions:
        op = str(operator)
        try:
            if op == "q":
                stack.append(ctm)
            elif op == "Q":
                ctm = stack.pop() if stack else _IDENTITY
            elif op == "cm":
                ctm = _multiply(tuple(numbers(operands)), ctm)
            elif op == "BT":
                text_matrix = line_matrix = _IDENTITY
            elif op == "Tm":
                text_matrix = line_matrix = tuple(numbers(operands))
            elif op == "TL":
                leading = numbers(operands)[0]
            elif op in ("Td", "TD"):
                tx, ty = numbers(operands)
                if op == "TD":
                    leading = -ty
                line_matrix = _multiply((1, 0, 0, 1, tx, ty), line_matrix)
                text_matrix = line_matrix
            elif op == "T*":
                line_matrix = _multiply((1, 0, 0, 1, 0, -leading), line_matrix)
                text_matrix = line_matrix
            elif op in _SHOWS_TEXT:
                if op in ("'", '"'):
                    line_matrix = _multiply((1, 0, 0, 1, 0, -leading), line_matrix)
                    text_matrix = line_matrix
                text_points.append(_apply(_multiply(text_matrix, ctm), 0, 0))
            elif op == "Do":
                name = str(operands[0])
                target = xobjects.get(name)
                if target is not None and target.get("/Subtype") == "/Image":
                    # An image is drawn into the unit square, so the current
                    # transform is its placement.
                    corners = [_apply(ctm, x, y)
                               for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
                    image_boxes.append((
                        min(x for x, _ in corners), min(y for _, y in corners),
                        max(x for x, _ in corners), max(y for _, y in corners),
                    ))
        except (ValueError, TypeError, IndexError):
            # One malformed operand must not lose the rest of the page.
            continue

    return text_points, image_boxes


def _check_barcode_zone(report, pdf, geometry):
    """Nothing may be printed where KDP prints the barcode.

    The README listed this under "what it guarantees" and nothing implemented
    it: `grep -c barcode preflight.py` was 0. The geometry was computed, and
    used to place the blurb, and never checked against the finished file - so a
    cover template that put a line of type there, or artwork supplied with
    --cover-image, would have been reported clear.
    """
    x, y, width, height = geometry.barcode_zone
    left, bottom = x * PT_PER_INCH, y * PT_PER_INCH
    right, top = left + width * PT_PER_INCH, bottom + height * PT_PER_INCH

    measured = _ink(pdf.pages[0])
    if measured is None:
        report.add(
            "Barcode zone clear", False, INFO,
            "not checked - this cover's content stream could not be read",
            "Open the back cover and check that nothing sits in the lower "
            f"right {width}\" x {height}\" of the panel.",
        )
        return

    text_points, image_boxes = measured
    inside = [p for p in text_points if left <= p[0] <= right and bottom <= p[1] <= top]
    overlapping = [b for b in image_boxes
                   if b[0] < right and b[2] > left and b[1] < top and b[3] > bottom]

    report.add(
        "Barcode zone clear of text", not inside, ERROR,
        f'the {width}" x {height}" zone on the back panel is clear'
        if not inside else f"{len(inside)} line(s) of text sit under the barcode",
        "KDP prints a barcode there whether or not you supply one, and it is "
        "printed over whatever is underneath. Shorten the blurb or move it up.",
    )
    if image_boxes:
        report.add(
            "Barcode zone legible", not overlapping, WARNING,
            "no artwork under the barcode" if not overlapping
            else f"{len(overlapping)} image(s) extend under the barcode",
            "A barcode over busy artwork can fail to scan. A plain, light "
            "patch behind it is what KDP asks for.",
        )


def preflight_cover(pdf_path, geometry):
    """Check a cover PDF against its computed geometry."""
    pdf_path = pathlib.Path(pdf_path)
    report = PreflightReport(target=pdf_path.name)

    _check_filename(report, pdf_path)
    _check_size(report, pdf_path)

    with pikepdf.open(pdf_path) as pdf:
        _check_encryption(report, pdf)

        single = len(pdf.pages) == 1
        report.add(
            "Single page", single, ERROR,
            f"{len(pdf.pages)} page(s)",
            "A cover must be one page containing back, spine and front together.",
        )
        if single:
            box = [float(v) for v in pdf.pages[0].MediaBox]
            got = ((box[2] - box[0]) / 72, (box[3] - box[1]) / 72)
            matches = (abs(got[0] - geometry.width) < 0.02
                       and abs(got[1] - geometry.height) < 0.02)
            report.add(
                "Cover size matches geometry", matches, ERROR,
                f'{got[0]:.3f}" x {got[1]:.3f}" '
                f'(expected {geometry.width:.3f}" x {geometry.height:.3f}")',
                f"The cover must be exactly back + spine + front plus bleed, "
                f"for a {geometry.pages}-page book.",
            )
            _check_cover_has_content(report, pdf)
            _check_barcode_zone(report, pdf, geometry)

        _check_fonts(report, pdf)
        _check_annotations(report, pdf)
        _check_metadata(report, pdf)
        _check_images(report, pdf)
        _check_transparency(report, pdf)

    return report
