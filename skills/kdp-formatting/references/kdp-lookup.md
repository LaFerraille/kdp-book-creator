# Which KDP topic answers which question

The files live in the plugin's `wiki/topics/` (build it first with `kdp wiki
build`); `kdp wiki search` prints each one's full path. Read one file, not the
index's worth.

| Question | Topic |
|---|---|
| Trim sizes, page-count limits, bleed, margins | `set-trim-size-bleed-and-margins.md` |
| Cover size, spine formula, spine text, barcode | `create-a-paperback-cover.md` |
| Hardcover wrap, hinge, headband, case | `create-a-hardcover-cover.md` |
| File rules, fonts, DPI, causes of rejection | `paperback-submission-guidelines.md` |
| Font choice and minimum size | `paperback-fonts.md` |
| Front matter, body matter, back matter | `format-front-matter-body-matter-and-back-matter.md` |
| Images, resolution, placement | `format-images-in-your-book.md` |
| Ebook manuscript rules | `ebook-manuscript-formatting-guide.md` |
| Ebook cover image | `what-criteria-does-my-ebooks-cover-image-need-to-meet.md` |
| Printing cost | `paperback-printing-cost.md`, `hardcover-printing-cost.md` |
| ISBN | `get-an-isbn.md`, `troubleshoot-isbn-errors.md` |
| Royalties | `paperback-royalty.md`, `ebook-royalties.md` |
| What KDP allows to be published | `content-guidelines.md` |
| Accessibility | `accessibility-guidelines.md` |

Anything else: `kdp wiki search "<question>"` ranks topics over the whole
graph and names their linked neighbours. Every KDP topic ID also resolves
through `wiki/index.json`.
