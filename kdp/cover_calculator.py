"""Cross-check cover geometry against KDP's live calculator, and fetch its template.

This is a *verification* step, never the build's critical path. The geometry we
draw with is computed offline from KDP's published formulas, because that is
deterministic, unit-testable and works with no network. Driving a live web page
is none of those things.

It earns its place for two reasons the formulas cannot cover:

1. **The official template.** The calculator generates a PNG/PDF with guide
   layers - safe areas, fold lines, barcode zone - which is a real artifact no
   formula produces and which a cover designer actually wants.
2. **A regression alarm on Amazon's own specifications.** If our arithmetic and
   the calculator ever disagree, KDP has changed something and we find out
   immediately, instead of after a rejected upload.

The form cascades: each dropdown stays disabled until the ones before it are
set, in the order binding, interior, paper, reading direction, units, trim
size, and only then does the page-count field unlock. Reading direction and
units are easy to skip and silently block everything after them.
"""
import pathlib
import re
from dataclasses import dataclass, field

URL = "https://kdp.amazon.com/en_US/cover-calculator"

# Labels as the live form writes them, keyed by our own vocabulary.
INTERIOR_LABELS = {
    "white": "Black & white", "cream": "Black & white", "groundwood": "Black & white",
    "standard_color": "Standard color", "premium_color": "Premium color",
}
PAPER_LABELS = {
    "white": "White paper", "cream": "Cream paper", "groundwood": "Groundwood",
    "standard_color": "White paper", "premium_color": "White paper",
}


class CalculatorUnavailable(RuntimeError):
    """Playwright missing, no network, or the page changed shape."""


@dataclass
class CalculatorResult:
    full_cover: tuple = ()          # (width, height) in inches
    front_cover: tuple = ()
    safe_area: tuple = ()
    bleed: tuple = ()
    spine: tuple = ()
    spine_safe_area: tuple = ()
    spine_margin: tuple = ()
    barcode_margin: tuple = ()
    template_path: str | None = None
    raw_rows: dict = field(default_factory=dict)

    def compare(self, geometry, tolerance=0.01):
        """Differences between KDP's numbers and ours, as readable strings.

        An empty list means the two agree. Anything in it means KDP has changed
        a specification, or we have a bug - either way a human needs to look.
        """
        problems = []
        checks = [
            ("full cover width", self.full_cover[0] if self.full_cover else None, geometry.width),
            ("full cover height", self.full_cover[1] if self.full_cover else None, geometry.height),
            ("spine width", self.spine[0] if self.spine else None, geometry.spine),
        ]
        for name, theirs, ours in checks:
            if theirs is None:
                problems.append(f"{name}: the calculator returned no value")
            elif abs(theirs - ours) > tolerance:
                problems.append(
                    f"{name}: KDP says {theirs:.4f}\", we compute {ours:.4f}\""
                )
        return problems


_ROW = re.compile(
    r"^\s*\d+\s+(?P<label>[A-Za-z ]+?)\s+(?P<w>\d+\.?\d*)\s+(?P<h>\d+\.?\d*)\s*$"
)

_FIELD_FOR = {
    "full cover": "full_cover",
    "front cover": "front_cover",
    "safe area": "safe_area",
    "bleed": "bleed",
    "spine": "spine",
    "spine safe area": "spine_safe_area",
    "spine margin": "spine_margin",
    "barcode margin": "barcode_margin",
}


def parse_results(text):
    """Pull the dimensions table out of the page's rendered text.

    Parsing text rather than the DOM deliberately: the table's markup is
    Amazon's to change, but the printed numbers are the thing a human would
    read off the page, and the row shape is far more stable than its classes.
    """
    result = CalculatorResult()
    for line in text.split("\n"):
        m = _ROW.match(line.replace("\t", " "))
        if not m:
            continue
        label = " ".join(m.group("label").split()).lower()
        value = (float(m.group("w")), float(m.group("h")))
        result.raw_rows[label] = value
        field_name = _FIELD_FOR.get(label)
        if field_name:
            setattr(result, field_name, value)
    return result


def _unpack(archive):
    """Extract KDP's template zip and return the PDF inside it, if there is one."""
    import zipfile

    if archive.suffix.lower() != ".zip":
        return None
    target = archive.with_suffix("")
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    except zipfile.BadZipFile:
        return None
    pdfs = sorted(target.glob("*.pdf"))
    return pdfs[0] if pdfs else target


def _pick(page, element_id, wanted, timeout_ms=10_000):
    """Choose an option, waiting for the cascade to enable the dropdown first."""
    waited = 0
    while waited < timeout_ms:
        element = page.query_selector(f"#{element_id}")
        if element is not None and element.is_enabled():
            break
        page.wait_for_timeout(300)
        waited += 300
    else:
        raise CalculatorUnavailable(
            f"{element_id} never became enabled - the form's cascade order may "
            f"have changed."
        )

    for option in page.query_selector_all(f"#{element_id} option"):
        text = " ".join((option.inner_text() or "").split())
        if wanted.lower() in text.lower():
            page.select_option(f"#{element_id}", value=option.get_attribute("value"))
            page.wait_for_timeout(800)
            return text
    raise CalculatorUnavailable(f"{element_id}: no option matching {wanted!r}")


def fetch(trim_w, trim_h, pages, paper, binding="paperback",
          download_template=False, outdir=None, headless=True, timeout_ms=60_000):
    """Drive the live calculator and return what it reports.

    Raises CalculatorUnavailable for anything that makes this impossible -
    missing Playwright, no network, a changed page. Callers treat that as
    "verification skipped", never as a build failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CalculatorUnavailable(
            "Playwright is not installed. It is optional: install it with "
            "`uv pip install -r requirements-dev.txt && python -m playwright install chromium` "
            "to cross-check geometry and download KDP's official template."
        ) from exc

    outdir = pathlib.Path(outdir) if outdir else pathlib.Path.cwd()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            page = browser.new_page(accept_downloads=True)
            page.goto(URL, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(2500)

            _pick(page, "binding-type-dropdown",
                  "Hardcover" if binding == "hardcover" else "Paperback")
            _pick(page, "interior-type-dropdown", INTERIOR_LABELS[paper])
            _pick(page, "paper-type-dropdown", PAPER_LABELS[paper])
            # Skipping either of these leaves everything after them disabled.
            _pick(page, "reading-direction-dropdown", "Left to Right")
            _pick(page, "measurement-units-dropdown", "Inches")
            _pick(page, "trim-size-dropdown", f"{trim_w:g} x {trim_h:g}")

            page.fill("#page-count-input", str(pages))
            page.dispatch_event("#page-count-input", "change")
            page.keyboard.press("Tab")
            page.wait_for_timeout(1200)

            calculate = page.query_selector("input[aria-labelledby=calculate-button-announce]")
            if calculate is None or not calculate.is_enabled():
                raise CalculatorUnavailable("the Calculate dimensions button never enabled")
            calculate.click()
            page.wait_for_timeout(5000)

            result = parse_results(page.inner_text("body"))
            if not result.full_cover:
                raise CalculatorUnavailable(
                    "the results table could not be read; the page layout may have changed"
                )

            if download_template:
                button = page.query_selector(
                    "input[aria-labelledby=cover-template-generate-button-announce]"
                )
                if button is not None and button.is_enabled():
                    with page.expect_download(timeout=timeout_ms) as info:
                        button.click()
                    download = info.value
                    outdir.mkdir(parents=True, exist_ok=True)
                    dest = outdir / (download.suggested_filename or "kdp-cover-template")
                    download.save_as(dest)
                    # KDP ships the template as a zip holding a PDF, a PNG and
                    # a readme. Unpack it: the PDF is what a designer opens,
                    # and leaving a zip for them to find is needless friction.
                    result.template_path = str(_unpack(dest) or dest)

            browser.close()
            return result

    except CalculatorUnavailable:
        raise
    except Exception as exc:                       # network, timeout, page change
        raise CalculatorUnavailable(f"could not reach KDP's calculator: {exc}") from exc


def verify(geometry, paper, **kw):
    """Compare our computed geometry with KDP's. Returns (result, problems).

    ``problems`` empty means they agree. A CalculatorUnavailable is allowed to
    propagate: the caller decides whether skipping verification is acceptable,
    because for an offline build it always is.
    """
    result = fetch(geometry.trim_w, geometry.trim_h, geometry.pages, paper,
                   binding=geometry.binding, **kw)
    return result, result.compare(geometry)
