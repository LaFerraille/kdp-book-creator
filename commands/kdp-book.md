---
description: Format a manuscript into upload-ready KDP paperback, hardcover and ebook files
argument-hint: <manuscript.md|.docx|.html|.txt>
---

Format `$1` into upload-ready Amazon KDP files.

Use the `kdp-formatting` skill. Follow its interview: analyse first and report
what you found before asking anything, give every question a default, and let
"I don't know" be a valid answer to all of them.

Never change the author's words. This is formatting only.

First, `kdp wiki status`: if the KDP wiki is not built yet, run
`kdp wiki build` before anything else, since every KDP rule is looked up there.

If `$1` is empty, run `kdp find .` and ask which of those is the book.

Markdown, DOCX, plain text and HTML all work. If a build fails for an
environmental reason — no LaTeX engine, a missing font — run `kdp doctor`
and report what it says needs installing rather than guessing.
