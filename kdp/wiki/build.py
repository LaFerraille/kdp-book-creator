"""Turn the cached KDP help HTML into a clean markdown wiki plus an index.

Outputs (all under wiki/):
  topics/<slug>.md  one markdown file per help topic, with YAML front matter
  index.json        the machine-readable navigation arborescence
  INDEX.md          the compact human/agent-facing index (titles + paths only)
"""
import hashlib
import json
import re
import unicodedata

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

from . import CACHE, TOPIC_RE, TOPICS, WIKI


# --------------------------------------------------------------------------
# slugs
# --------------------------------------------------------------------------
def slugify(title, tid):
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\s-]", "", t).strip().lower()
    t = re.sub(r"[\s_-]+", "-", t)
    t = t[:70].strip("-")
    return t or tid.lower()


def write_if_changed(path, text):
    """Only touch a file whose content actually changed.

    Rewriting all ~280 files on every build makes file-sync clients (iCloud
    Drive, Dropbox) race the rebuild and drop "<name> 2.md" conflict copies
    into the tree. It also keeps `git status` honest about what a build did.
    """
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


# --------------------------------------------------------------------------
# html -> markdown
# --------------------------------------------------------------------------
class KDPConverter(MarkdownConverter):
    """markdownify tuned for KDP help pages."""

    def __init__(self, slug_for, **kw):
        super().__init__(**kw)
        self.slug_for = slug_for

    def convert_a(self, el, text, parent_tags=None):
        href = el.get("href", "") or ""
        # Collapsible-section toggles are links to nowhere; keep only the label.
        if href.startswith("javascript:") or href == "#":
            t = text.strip()
            if not t:
                return ""
            # the label is often already bold in the source - don't re-wrap it
            return t if t.startswith("**") and t.endswith("**") else f"**{t}**"
        m = TOPIC_RE.search(href)
        if m:
            slug = self.slug_for(m.group(1))
            if slug:
                el["href"] = f"./{slug}.md"
            else:  # topic we never managed to fetch - point at the live page
                el["href"] = f"https://kdp.amazon.com/en_US/help/topic/{m.group(1)}"
        elif href.startswith("/"):
            el["href"] = "https://kdp.amazon.com" + href
        return super().convert_a(el, text, parent_tags)

    def convert_iframe(self, el, text, parent_tags=None):
        src = el.get("src", "")
        if not src:
            return ""
        if src.startswith("//"):
            src = "https:" + src
        return f"\n\n[Embedded video]({src})\n\n"

    def convert_img(self, el, text, parent_tags=None):
        src = el.get("src", "")
        if src.startswith("//"):
            el["src"] = "https:" + src
        elif src.startswith("/"):
            el["src"] = "https://kdp.amazon.com" + src
        return super().convert_img(el, text, parent_tags)


def tidy(md):
    """Normalise the whitespace soup that markdownify leaves behind."""
    md = md.replace("​", "").replace("\xa0", " ")
    # trailing hard-break spaces on otherwise empty lines
    md = re.sub(r"(?m)^[ \t]+$", "", md)
    md = re.sub(r"(?m)[ \t]+$", "", md)
    # a rule right after a heading, or stacked rules, add nothing
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"(?m)^(---\n)(\n*---\n)+", r"\1", md)
    # A couple of pages have the feedback widget inside .help-body rather than
    # in the page chrome around it; it is not documentation.
    md = re.sub(r"(?m)^#{1,6}\s*\**Was this article helpful.*$", "", md)
    return fix_tables(md).strip() + "\n"


SEP_RE = re.compile(r"^\s*\|(\s*:?-+:?\s*\|)+\s*$")


def _cells(row):
    return row.strip().strip("|").split("|")


def _normalise_table(block):
    """Give a markdown table exactly one separator row, under its first row.

    KDP builds most tables out of <td> only, so markdownify prefixes them with
    an empty header row. Dropping that row without moving the separator leaves
    a block that no longer parses as a table, so do both together.
    """
    if (len(block) >= 2 and SEP_RE.match(block[1])
            and all(c.strip() == "" for c in _cells(block[0]))):
        block = block[2:]           # empty header + its separator
    else:
        block = [r for r in block if not SEP_RE.match(r)]
    if not block:
        return []
    ncol = max(len(_cells(r)) for r in block)
    sep = "| " + " | ".join(["---"] * ncol) + " |"
    return [block[0], sep] + block[1:]


def fix_tables(md):
    lines, out, i = md.split("\n"), [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            start = i
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                i += 1
            out.extend(_normalise_table(lines[start:i]))
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


# --------------------------------------------------------------------------
# navigation tree
# --------------------------------------------------------------------------
def parse_nav(soup):
    """Rebuild the arborescence from the sidebar's nested <ul class="help-nav">.

    The eleven level-0 entries are section *headers* (`.topic-group-title`:
    "Book Formatting", "Payments & Reports", ...), not topics - they carry no
    link of their own. Everything below them is a real topic. The section names
    are the ones KDP itself shows in each page's breadcrumb.
    """

    def walk(ul):
        out = []
        for li in ul.find_all("li", class_="help-nav-item", recursive=False):
            span = li.find("span", class_="a-list-item", recursive=False)
            if span is None:
                continue
            group = span.find(class_="topic-group-title", recursive=False)
            a = span.find("a", recursive=False)
            if group is not None:
                node = {"id": None, "title": group.get_text(" ", strip=True),
                        "children": []}
            elif a is not None:
                m = TOPIC_RE.search(a.get("href", ""))
                node = {"id": m.group(1) if m else None,
                        "title": a.get_text(" ", strip=True), "children": []}
            else:
                continue
            sub = span.find("ul", class_="help-nav", recursive=False)
            if sub is not None:
                node["children"] = walk(sub)
            out.append(node)
        return out

    root = soup.select_one("ul.help-nav.level-0")
    tree = walk(root) if root else []

    # A topic that also acts as a section landing page is listed twice: once as
    # the parent and again as its own first child. Fold the repeat away, keeping
    # whichever copy carries the children.
    def dedupe(nodes):
        for n in nodes:
            kids = n["children"]
            if kids and kids[0]["id"] is not None and kids[0]["id"] == n["id"]:
                n["children"] = kids[0]["children"] + kids[1:]
            dedupe(n["children"])
        return nodes

    return dedupe(tree)


# --------------------------------------------------------------------------
def build():
    """Turn wiki/.cache into topics/, index.json and INDEX.md. Returns the
    number of topics written."""
    if not (CACHE / "_manifest.json").exists():
        raise FileNotFoundError("No cached help pages. Run `kdp wiki build`.")

    manifest = json.loads((CACHE / "_manifest.json").read_text(encoding="utf-8"))
    ids = manifest["topic_ids"]

    # Pass 1: read every page, collect titles/breadcrumbs, decide slugs.
    pages = {}
    for tid in ids:
        f = CACHE / f"{tid}.html"
        if not f.exists():
            continue
        soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
        body = soup.select_one(".help-body") or soup.select_one("#help-content")
        title_el = soup.select_one(".help-title") or soup.find("h1")
        crumb_el = soup.select_one(".help-breadcrumb")
        title = title_el.get_text(" ", strip=True) if title_el else tid
        crumbs = []
        if crumb_el:
            crumbs = [c.get_text(" ", strip=True)
                      for c in crumb_el.find_all(["a", "span", "li"])
                      if c.get_text(strip=True)]
            # de-duplicate consecutive repeats the markup sometimes produces
            crumbs = [c for i, c in enumerate(crumbs) if i == 0 or c != crumbs[i - 1]]
        pages[tid] = {"title": title, "crumbs": crumbs, "body": body,
                      "text": body.get_text(" ", strip=True) if body else ""}

    # Pass 2: navigation tree (from any cached page - they all carry it).
    root_soup = BeautifulSoup((CACHE / "_root.html").read_text(encoding="utf-8"),
                              "html.parser")
    tree = parse_nav(root_soup)

    in_nav = set()

    def collect(nodes):
        for n in nodes:
            if n["id"]:
                in_nav.add(n["id"])
            collect(n["children"])

    collect(tree)

    # Pass 2b: KDP serves the same article under several legacy ids (old ASIN-
    # style node ids, un-prefixed numeric ids, retired slugs). Group pages by
    # content and keep one canonical id per group so the wiki has one file per
    # actual topic, with the rest recorded as aliases.
    # Retired topics still resolve, but KDP serves a "This page is unavailable"
    # placeholder instead of content. Those are not worth a wiki page.
    stubs = {t for t, p in pages.items()
             if len(p["text"]) < 60 or p["text"].startswith("This page is unavailable")}
    for t in stubs:
        pages.pop(t)

    groups = {}
    for tid, p in pages.items():
        digest = hashlib.sha1((p["title"] + "\x00" + p["text"]).encode()).hexdigest()
        groups.setdefault(digest, []).append(tid)

    def rank(tid):
        # lowest sorts best: in the sidebar > G-prefixed > anything else
        return (tid not in in_nav, not tid.startswith("G"), -len(tid), tid)

    canonical_of, aliases_of = {}, {}
    for members in groups.values():
        best = min(members, key=rank)
        aliases_of[best] = sorted(t for t in members if t != best)
        for t in members:
            canonical_of[t] = best

    canonicals = sorted(aliases_of, key=lambda t: pages[t]["title"].lower())

    used, slug_of = {}, {}
    for tid in canonicals:
        base = slugify(pages[tid]["title"], tid)
        slug = base
        if slug in used:  # genuinely different topics can share a title
            slug = f"{base}-{tid.lower()}"
        used[slug] = tid
        slug_of[tid] = slug

    def resolve(tid):
        """Any id -> the slug of the file that holds its content."""
        return slug_of.get(canonical_of.get(tid, tid))

    def mark(nodes):
        for n in nodes:
            n["slug"] = resolve(n["id"])
            mark(n["children"])

    mark(tree)

    nav_covered = {canonical_of[t] for t in in_nav if t in canonical_of}
    orphans = [t for t in canonicals if t not in nav_covered]

    # Pass 3: write the markdown files.
    TOPICS.mkdir(parents=True, exist_ok=True)

    conv = KDPConverter(slug_for=resolve,
                        heading_style="ATX", bullets="-", escape_underscores=False,
                        escape_asterisks=False)
    written = 0
    for tid in canonicals:
        p = pages[tid]
        md = tidy(conv.convert_soup(p["body"])) if p["body"] else "*(no content)*\n"
        fm = [
            "---",
            f"id: {tid}",
            f"title: {json.dumps(p['title'])}",
            f"slug: {slug_of[tid]}",
            f"breadcrumb: {json.dumps(' > '.join(p['crumbs']))}",
            f"source: https://kdp.amazon.com/en_US/help/topic/{tid}",
        ]
        if aliases_of[tid]:
            fm.append(f"aliases: [{', '.join(aliases_of[tid])}]")
        fm += ["---", "", f"# {p['title']}", ""]
        write_if_changed(TOPICS / f"{slug_of[tid]}.md", "\n".join(fm) + md)
        written += 1

    # Remove files left over from a previous build (renamed or retired topics).
    wanted = {f"{slug_of[t]}.md" for t in canonicals}
    for stale in TOPICS.glob("*.md"):
        if stale.name not in wanted:
            stale.unlink()

    # Pass 4: index.json + INDEX.md
    index = {
        "source": "https://kdp.amazon.com/en_US/help/",
        "fetched_at": manifest["fetched_at"],
        "topic_count": written,
        "tree": tree,
        "unlinked_topics": [  # reachable only from in-body cross references
            {"id": t, "title": pages[t]["title"], "slug": slug_of[t]} for t in orphans
        ],
        # every id KDP will accept -> the file that answers it
        "id_to_slug": {t: slug_of[c] for t, c in sorted(canonical_of.items())
                       if c in slug_of},
        "dropped_empty_ids": sorted(stubs),
    }
    write_if_changed(WIKI / "index.json", json.dumps(index, indent=1))

    lines = [
        "# Amazon KDP Help — Topic Index",
        "",
        f"Mirror of <https://kdp.amazon.com/en_US/help/> — {written} topics, "
        f"fetched {manifest['fetched_at']}.",
        "",
        "Each entry below links to a markdown file in `topics/`. **Read only the "
        "topics you need** — this index is the map, the files are the territory. "
        "Regenerate with `kdp wiki build --refresh`.",
        "",
    ]

    def emit(nodes, depth=0):
        for n in nodes:
            pad = "  " * depth
            if n.get("slug"):
                lines.append(f"{pad}- [{n['title']}](topics/{n['slug']}.md)")
            else:
                lines.append(f"{pad}- **{n['title']}**")
            emit(n["children"], depth + 1)

    emit(tree)
    if orphans:
        lines += ["", "## Not in the sidebar navigation", "",
                  "Reached only through in-body cross references:", ""]
        for t in sorted(orphans, key=lambda x: pages[x]["title"]):
            lines.append(f"- [{pages[t]['title']}](topics/{slug_of[t]}.md)")
    write_if_changed(WIKI / "INDEX.md", "\n".join(lines) + "\n")

    print(f"{written} topics, {len(tree)} sections, {len(orphans)} reachable "
          f"only by cross-reference; {len(canonical_of) - written} alias ids "
          f"folded in, {len(stubs)} empty stubs dropped")
    return written
