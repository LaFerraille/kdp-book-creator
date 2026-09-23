---
name: kdp-formatting
description: Use when someone wants a finished manuscript formatted into a printable or publishable book, mentions Amazon KDP, self-publishing, a paperback or hardcover interior, a book cover's spine, or asks about trim size, bleed, gutter margins, page-count limits, KDP's publishing rules, or why KDP rejected an uploaded file. Formatting only - never for writing or editing the book's text.
---

# KDP book formatting

Turn a finished manuscript into upload-ready KDP files. **Format only — never
add, cut, or rewrite the author's words.** Not a line of the book is written
here; literature stays in human hands.

## Setup: the `kdp` command and the wiki

Installed as a Claude Code plugin, `kdp` is on PATH (`${CLAUDE_PLUGIN_ROOT}/bin/kdp`)
and creates its own virtualenv the first time it runs. Installed as a bare
skill, fetch the engine once and call it by path:

```bash
git clone https://github.com/LaFerraille/kdp-book-creator ~/.kdp-book-creator
~/.kdp-book-creator/bin/kdp doctor
```

**Build the KDP wiki before anything else.** `kdp wiki status` says whether it
exists; if not, run `kdp wiki build` (a few minutes, once). It scrapes the whole
KDP Help Center to this machine and indexes it as a graph of topics, sections
and cross-references.

## Never guess a KDP rule

KDP rejects files over specifics, and changes them without notice. When a
specification matters, look it up in the wiki:

1. `kdp wiki search "<the question>"` — ranked topics, their files and linked neighbours
2. Open the one topic that answers it, at the path search prints, and cite its `source:` URL

`references/kdp-lookup.md` says which topic answers the most common questions.

## Never do arithmetic the tools already do

`kdp/` computes page counts, margins, spine width and cover geometry from
KDP's published formulas, and they are unit-tested against KDP's own worked
examples. An estimate you reason out will be wrong; these are not.

```bash
kdp doctor                  # can this machine build a book at all?
kdp find .                  # which file is the book?
kdp analyse manuscript.md   # what is this book, and how long will it be?
kdp build manuscript.md     # interior, cover, ebook, preflight
kdp cover --spec build/book.yaml --title "…" --author "…" --blurb "…"   # cover alone
kdp check some.pdf --spec build/book.yaml
kdp wiki search "gutter margin for 300 pages"
```

Markdown, DOCX, plain text and HTML all load. DOCX needs nothing installed;
`.odt`, `.rtf` and `.html` go through pandoc. A failure prints a sentence, not
a traceback — read it, it says what to do.

## The interview

Read `references/interview.md` for the eleven stages and what each one asks.

Four rules govern all of them:

0. **Find the manuscript, then confirm it.** If they did not name a file, run
   `find` and ask "is this the one?" — never guess silently, never demand a path.
1. **Detect before asking.** Stage 1 reports what was found and asks nothing.
2. **Every question has a default, and "I don't know" is always an option.**
   It resolves to `kdp/specs/book_defaults.yaml` and *says what was chosen
   and why*. `kdp build --book-type <type>` applies that whole row, so the
   book you describe is the book that gets built.
   Someone must be able to answer "not sure" to every question and still get a
   correct, good-looking book.
3. **Show the consequence, not the parameter.** Not "trim size?" but "6×9 gives
   about 316 pages, 5.5×8.5 about 352 and a thicker spine."
4. **Offer an escape at every stage:** "use sensible defaults for the rest".

## Exploring an unfamiliar manuscript

`analyse` measures what is countable. For what needs reading — genre, what the
italics are *for*, whether a passage is an epigraph — dispatch subagents over
the evidence packet:

```bash
kdp analyse manuscript.md --evidence build/evidence.json
```

Give agents that file, never the manuscript: a book does not fit in a context
window. **Measurement overrules agent judgement on anything countable** — they
will estimate page counts anyway, and they will be wrong.

## Common mistakes

| Mistake | What happens |
|---|---|
| Inventing a title from a chapter heading or a filename | The author gets a book named after its own last chapter. If the file does not state a title, ask — `build` will not make a cover without one. |
| Ignoring what `doctor` says about hyphenation | A book in a language whose patterns are missing is typeset with English word-breaking on every page, and passes every other check. |
| Reaching for `--allow-bad-hyphenation` to get past a refusal | It does exactly what it says: sets the book in English. Install the patterns `doctor` names, or pass `--language` if the manuscript was misread. |
| Answering an undetected language with a guess | `build` refuses rather than assuming English. Ask the author and pass `--language`; it is one of the two things no default can supply. |
| Building a manuscript that loaded with zero chapters | One undifferentiated block of text and an ebook KDP rejects. `build` refuses; find the chapter markers instead of forcing it. |
| Accepting inferred structure without confirming it | Plain text has no headings, so they are *guessed* from underlines and "ACT 1" lines. The guess is reported — show it to the author before building. |
| Debugging a failed build by reading LaTeX logs | Run `doctor` first. Most failures are a missing engine, package or font, and it names them. |
| Using KDP's minimum margins as design margins | Cramped, amateur-looking pages. Minimums are floors, not recommendations. |
| Letting the typesetter number self-numbered titles | "Chapitre 1. Chapitre 1 — La boutique" in every running head |
| Trusting an agent's page estimate | Wrong by 10–20%. Render and count. |
| Editing the author's file to fix inconsistencies | Normalise in memory instead; the manuscript is theirs. |
| Claiming a build is KDP-ready without preflight | `build` runs it automatically. Read the report. |
| Passing `--out` | Without it, files land in `build/` under the working directory, one predictable location. |
| Writing a blurb, a title or a dedication for the author | Not this tool's job. Ask for their words and use them verbatim. |
