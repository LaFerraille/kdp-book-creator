# The interview, stage by stage

Eleven stages, ordered so that decisions constraining later ones come first.
Stop early whenever the answer is "use sensible defaults for the rest".

## 0 — Find the manuscript

If they dropped a file in the chat or named a path, use it. Otherwise run
`kdp find .` and confirm: "I found my-book.md, about 100,000 words — is
that the one?" Never guess silently, and never make them hunt for a path.

If nothing is found, say which formats are accepted and ask for the file.

Run `kdp doctor` too, but only *report* it if something is missing.
Finding out at stage 10 that there is no LaTeX engine wastes the whole
interview; leading with a clean bill of health is noise.

## 1 — Analyse. Ask nothing.

Run `kdp analyse`. Report language, chapter and section counts, word
count, image count, the heading pattern, and anything odd. Finish with the
estimated page count, which `analyse` prints for three trim sizes. Opening
with detection earns trust that a questionnaire never will.

**If it reports inferred structure, stop and confirm it.** Plain text carries no
headings, so chapters are read from conventions — underlined titles, "ACT 1"
lines. Show what was found ("I read 5 acts and 20 scenes — right?") before
going further. Everything downstream is built on this being correct.

**If it found no chapters at all, do not build.** The result would be one
continuous block of text and an ebook KDP rejects. Ask how chapters are marked
in their file.

## 2 — What kind of book?

Keys every default in `kdp/specs/book_defaults.yaml`: novel, narrative
non-fiction, practical non-fiction, poetry, drama, children's, workbook. Offer
the detected hint.

Once it is settled, pass it: `kdp build --book-type narrative_nonfiction`
applies that whole row. Without it the build uses the class defaults — 6×9 with
no contents — which is a legal book but not the one you just described, and the
author ends up with something other than what you told them you had chosen.

## 3 — Identity

Title, subtitle, author, language. Language is detected — confirm rather than
ask.

**When it is not detected, ask, and pass `--language`.** `analyse` reports no
language when the evidence is thin, and `build` then refuses rather than
assuming English. That refusal is deliberate: English is the one wrong answer
with no visible symptom, because the book renders, passes every check, and has
its words broken in the wrong places on every page. The pipeline sets English,
French, Spanish, German, Italian and Portuguese; a manuscript in anything else
has to be said out loud, not worked around.

**The title is the author's, and is never inferred.** `analyse` reports one only
when the file states it: front matter, a title page, or the document's
properties. A chapter heading is not a title — taking one named a memoir after
its last chapter. Neither is a name that
recurs in the prose, however often.

If the file does not state a title, **ask**. With the blurb, it is one of the
two things no default can supply, and `build` refuses to make a cover without
it rather than printing a blank one.

## 4 — Which formats?

Paperback, hardcover, ebook. Default paperback + ebook.

## 5 — Trim size

Offer three, **each with its computed page count**. Mark the most common.
A smaller trim means more pages, a thicker spine, and a higher print cost.

## 6 — Paper and ink

Black and white unless the book has images. Cream for prose, white for
reference. Say what the cost difference is.

## 7 — Typography

**Ask nothing.** Set the default for the book type and offer *"want to see a
sample page?"* instead. Only people who ask get the knobs.

## 8 — Front and back matter

Report what is missing and offer to generate it: half-title, title page,
copyright page (needs year and rights holder), dedication, contents.

## 9 — Cover

Artwork on hand? If not, pick a template and a palette. Collect the back-cover
blurb. Spine text is automatic above KDP's page threshold.

## 10 — Build and report

Run `kdp build`. Report the page count, spine width, every preflight
check, and the files — **by name and by folder**, so they know what to upload
and where it is.

If a font is unavailable the build stops rather than substituting, because a
different font means a different page count and so a different spine. Offer the
fonts `doctor` lists, or `--font-fallback` if they would rather have the book
than the exact face. Files land in `build/` under the directory `kdp` was run
from, and are named after the book and what they are, for example
`hamlet-paperback-interior.pdf`. Offer to open the PDF.
Everything is written to `book.yaml` so a rebuild asks nothing.

## Anomalies

Surface them, never fix them silently, and separate the two kinds:

- **Cosmetic and safe to normalise at typesetting** (inconsistent zero-padding
  in chapter numbers). Say what was changed, and that their file is untouched.
- **Possibly deliberate** (one chapter far shorter than the rest — often a
  closing chapter). Ask. Changing it alters how the book reads, which is the
  author's call, not a formatting decision.
