---
description: Ask anything about KDP's rules, your book in progress, or what to do next, answered from the local KDP wiki
argument-hint: "<question>"
---

Answer: $ARGUMENTS

Use the `kdp-formatting` skill. Ground every answer; never answer from memory.

1. **Make sure the wiki exists.** `kdp wiki status`. If it is not built, run
   `kdp wiki build` first and say you are doing so.
2. **KDP rules and how-tos.** Run `kdp wiki search "<the question, in KDP's
   words>"`. Open the top one to three topic files it names, and follow a
   linked neighbour when the answer depends on it. Quote the numbers exactly
   and cite each topic's `source:` URL.
3. **The book in progress.** Read `build/book.yaml` (trim, paper, font, page
   count, spine) and the `*-preflight.md` reports in `build/`. For questions
   about the manuscript itself, run `kdp analyse <manuscript>`. Page counts,
   margins and spine widths come from these files or from `kdp`, never from
   arithmetic of your own.
4. **Next steps.** Combine the two: what the build shows is done, what
   preflight flags, and what KDP's publishing flow (search "title setup",
   "publishing review", "order proof copies") says comes next.

If the wiki has no topic that answers the question, say so. Do not fill the
gap with a guess. Never write, edit or suggest the book's text: this tool
formats books, it does not write them.
