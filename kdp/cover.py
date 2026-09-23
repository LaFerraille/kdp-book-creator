"""Draw a print-ready wrap cover: back panel, spine and front panel on one page.

Geometry comes from geometry.CoverGeometry, which derives it from KDP's
published formulas. This module only places ink inside that geometry. Keeping
the two apart means the arithmetic that decides whether a cover is rejectable
is unit-tested without rendering anything, and the drawing code cannot quietly
disagree with it.

Everything is positioned from the bottom-left of the cover in inches, matching
the coordinate system CoverGeometry exposes.
"""
import pathlib

from . import specs
from .fonts import resolve as resolve_font
from .latex import inline_to_latex
from .render_print import RenderError, _run_engine, _strip_metadata, find_engine

# One cover, and no ornament on it. The band and the rule that used to live
# here were decoration applied to a layout that had not been solved - a gold
# line ruled across an empty middle third. Type placed well on a plain ground
# is what a restrained trade cover is; a line across it is what it looks like
# when something is missing.
TEMPLATES = ("plain",)


class CoverError(RuntimeError):
    pass


def build_cover_latex(geometry, meta, *, template="plain", background=None,
                      bg_color="1a1a1a", fg_color="ffffff",
                      font="Palatino", blurb="", spine_text=None):
    """Generate the .tex for a full wrap cover.

    ``background`` is an optional image placed across the whole cover, already
    sized by the caller. Text is drawn over it either way.
    """
    if template not in TEMPLATES:
        raise CoverError(f"unknown cover template {template!r}; expected one of {TEMPLATES}")

    g = geometry
    front_x = g.front_panel_x
    back_x = g.back_panel_x
    spine_x = g.spine_x

    # Centre lines of each panel, used for horizontal centring.
    front_mid = front_x + g.trim_w / 2
    back_mid = back_x + g.trim_w / 2
    spine_mid = spine_x + g.spine / 2

    title = inline_to_latex(meta.title or "")
    subtitle = inline_to_latex(meta.subtitle or "")
    author = inline_to_latex(meta.author or "")
    blurb_tex = inline_to_latex(blurb or "")

    parts = [
        r"\documentclass[12pt]{article}",
        r"\usepackage[paperwidth=%.4fin,paperheight=%.4fin,margin=0in]{geometry}"
        % (g.width, g.height),
        r"\usepackage{tikz}",
        r"\usetikzlibrary{calc}",
        r"\usepackage{fontspec}",
        resolve_font(font).latex,
        r"\definecolor{bg}{HTML}{%s}" % bg_color.upper().lstrip("#"),
        r"\definecolor{fg}{HTML}{%s}" % fg_color.upper().lstrip("#"),
        r"\pagestyle{empty}",
        r"\setlength{\parindent}{0pt}",
        # A hyphenated word on a cover looks like a mistake. Done with
        # penalties rather than the hyphenat package, to keep the plugin's
        # TeX dependencies to what a minimal TinyTeX already ships.
        r"\hyphenpenalty=10000\exhyphenpenalty=10000\tolerance=2000",
        r"\begin{document}",
        r"\begin{tikzpicture}[remember picture,overlay,x=1in,y=1in]",
        # Origin at the bottom-left corner of the page.
        r"\coordinate (O) at (current page.south west);",
    ]

    if background:
        parts.append(
            r"\node[anchor=south west,inner sep=0] at (O) "
            r"{\includegraphics[width=%.4fin,height=%.4fin]{%s}};" % (g.width, g.height, background)
        )
    else:
        parts.append(
            r"\fill[bg] (O) rectangle ++(%.4f,%.4f);" % (g.width, g.height)
        )

    # --- front panel ----------------------------------------------------
    # Proportions rather than fixed offsets, so a 5x8 and an 8.5x11 cover are
    # the same design at two sizes instead of two different accidents.
    #
    # The title block hangs from 28% of the height. That is above the
    # mathematical centre, which is where a title has to sit to look centred:
    # the eye reads the optical centre as higher than the true one, and type
    # placed at 50% appears to sag. The author sits a comfortable step in from
    # the foot rather than against it, and the two are placed relative to the
    # panel, which is what stops the middle reading as a gap with a line
    # through it.
    text_w = g.trim_w * 0.74
    title_pt = max(22.0, min(44.0, g.trim_w * 6.2))
    author_pt = max(11.0, title_pt * 0.42)
    subtitle_pt = max(10.0, title_pt * 0.36)

    title_y = g.height - g.edge - (g.trim_h * 0.28)
    parts.append(
        r"\node[anchor=north,text=fg,align=center,text width=%.4fin] at ($(O)+(%.4f,%.4f)$) "
        r"{\fontsize{%.1f}{%.1f}\selectfont %s};"
        % (text_w, front_mid, title_y, title_pt, title_pt * 1.18, title)
    )
    if subtitle:
        parts.append(
            r"\node[anchor=north,text=fg,align=center,text width=%.4fin] at ($(O)+(%.4f,%.4f)$) "
            r"{\fontsize{%.1f}{%.1f}\selectfont\itshape %s};"
            % (text_w, front_mid, title_y - (title_pt * 1.9 / 72.0),
               subtitle_pt, subtitle_pt * 1.25, subtitle)
        )
    if author:
        parts.append(
            r"\node[anchor=south,text=fg,align=center,text width=%.4fin] at ($(O)+(%.4f,%.4f)$) "
            r"{\fontsize{%.1f}{%.1f}\selectfont %s};"
            % (text_w, front_mid, g.edge + (g.trim_h * 0.10),
               author_pt, author_pt * 1.25, author)
        )

    # --- spine ----------------------------------------------------------
    # Text is only permitted above KDP's page threshold, and only if the spine
    # is physically wide enough to hold type with its clearance either side.
    clearance = specs.constants()["paperback_cover"]["spine_text_clearance"]
    spine_fits = g.spine - 2 * clearance >= 0.08
    if spine_text is not False and g.allows_spine_text and spine_fits:
        # Escape each part separately, then join with a real LaTeX command.
        # Escaping the joined string turns the separator into a literal
        # "\quad" on the printed spine.
        if spine_text:
            label = inline_to_latex(spine_text)
        else:
            label = r" \quad\textperiodcentered\quad ".join(
                inline_to_latex(x) for x in (meta.title, meta.author) if x
            )
        pt = max(7, min(14, (g.spine - 2 * clearance) * 62))
        parts.append(
            r"\node[rotate=-90,text=fg,anchor=center] at ($(O)+(%.4f,%.4f)$) "
            r"{\fontsize{%.1f}{%.1f}\selectfont %s};"
            % (spine_mid, g.height / 2, pt, pt * 1.2, label)
        )

    # --- back panel -----------------------------------------------------
    if blurb_tex:
        # Sized and placed like the front, and stopped above the barcode: KDP
        # prints one there whether or not you supply it, and text underneath
        # would be printed over.
        _, zone_y, _, zone_h = barcode_zone(g)
        blurb_pt = max(9.5, g.trim_w * 1.85)
        blurb_top = g.height - g.edge - (g.trim_h * 0.16)
        available = blurb_top - (zone_y + zone_h) - 0.2
        parts.append(
            r"\node[anchor=north,text=fg,align=left,text width=%.4fin,"
            r"minimum height=%.4fin] at ($(O)+(%.4f,%.4f)$) "
            r"{\fontsize{%.1f}{%.1f}\selectfont %s};"
            % (g.trim_w * 0.76, max(available, 0.5), back_mid, blurb_top,
               blurb_pt, blurb_pt * 1.42, blurb_tex)
        )

    parts += [r"\end{tikzpicture}", r"\end{document}"]
    return "\n".join(parts)


def barcode_zone(geometry):
    """The rectangle that must stay clear, as (x, y, width, height) in inches.

    The arithmetic lives on CoverGeometry, with the rest of what decides
    whether a cover is rejectable; this is here because placing the blurb and
    checking the finished file both ask the same question, and only one of them
    has a geometry object to hand.
    """
    return geometry.barcode_zone


def render_cover(geometry, meta, outdir, **kw):
    """Render the cover to a single-page PDF and return its path."""
    engine, _ = find_engine()
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    tex_path = outdir / "cover.tex"
    pdf_path = outdir / "cover.pdf"
    tex_path.write_text(build_cover_latex(geometry, meta, **kw), encoding="utf-8")

    # Twice, always: TikZ's `current page` node only exists on a pass that has
    # already seen the page shipped out, so a single pass draws everything at
    # the origin and the cover comes out nearly blank.
    result = None
    for _ in range(2):
        result = _run_engine(engine, tex_path, outdir)
    # As with the interior: a non-zero exit is a failure even if a PDF from an
    # earlier pass is still sitting on disk.
    if result.returncode != 0 or not pdf_path.exists():
        log = outdir / "cover.log"
        detail = (log.read_text(encoding="utf-8", errors="replace")[-1500:]
                  if log.exists() else result.stderr)
        raise RenderError(f"cover render failed:\n{detail}")

    _strip_metadata(pdf_path)
    return pdf_path
