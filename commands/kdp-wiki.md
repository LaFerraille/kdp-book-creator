---
description: Build (or refresh) the local KDP Help Center knowledge graph
argument-hint: "[--refresh]"
---

Build the KDP knowledge base the `kdp-formatting` skill looks every rule up in.

Run:

```bash
kdp wiki build $ARGUMENTS
```

It fetches every KDP Help Center topic to this machine (resumable, polite, a
few minutes the first time), converts them to Markdown under `wiki/topics/`,
and indexes them as a graph in `wiki/graph.json`: sections, topics, the
sidebar hierarchy and every in-body cross-reference.

Report the counts it prints. If it says KDP's trim-size or margin tables
changed, say so plainly: the specifications the build relies on moved, and
the diff in `kdp/specs/trim_sizes.json` needs a human look.

Then try it: `kdp wiki search "spine width cream paper"`.
