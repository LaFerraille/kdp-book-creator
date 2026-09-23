---
description: Build a KDP cover PDF at the exact geometry for a given page count
argument-hint: "[pages] [trim]"
---

Build a print-ready cover.

Use the `kdp-formatting` skill. The spine width depends on the final page
count, so the interior must be rendered first — if it has not been, say so and
offer to build it.

Collect the back-cover blurb and any artwork, then run:

```bash
kdp cover --spec build/book.yaml --title "…" --author "…" --blurb "…"
```

`book.yaml` carries the page count from the last build, so this costs seconds
rather than re-rendering the interior. Pass `--pages` to override it. A title is
required — the cover cannot be made without one, and it is not something to
guess from a chapter heading. Verify the
geometry against KDP's live calculator with `--verify-cover` when the network is
available, and hand over the official template it downloads.
