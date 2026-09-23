# Contributing

Thanks for helping. Two principles decide most questions here:

1. **Formatting, never writing.** This project typesets books; it does not write,
   edit, summarise or "improve" them. A pull request that generates, rewrites or
   suggests an author's text (titles, blurbs, dedications included) will not be
   merged, however it is framed.
2. **Never guess a KDP rule.** Every KDP number lives in `kdp/specs/`, cites the
   help topic it came from, and is tested against the local wiki. If you need a
   new one, add it there with its citation.

## Setup

Python 3.11 and [uv](https://docs.astral.sh/uv/). Nothing is installed from the
repository: `kdp` is a package at the root and runs from here.

```bash
git clone https://github.com/LaFerraille/kdp-book-creator
cd kdp-book-creator
uv venv && uv pip install -r requirements-dev.txt
python -m kdp doctor        # LaTeX engine, fonts, hyphenation patterns
python -m kdp wiki build    # the local KDP Help Center graph (a few minutes, once)
```

Please don't add a `pyproject.toml` or an editable install. On machines that
sync their home directory, the `.pth` file an editable install leaves behind
gets the hidden flag, and Python silently stops importing the package.

## Before you open a pull request

```bash
ruff check .
python -m pytest
```

The end-to-end tests need a LaTeX engine and skip without one; CI installs one
and fails if they skip. The tests that compare `kdp/specs/` against the wiki
skip until you have run `python -m kdp wiki build`.

## Layout

```
bin/kdp                     launcher Claude Code puts on PATH (creates its own venv)
commands/                   /kdp-book, /kdp-cover, /kdp-check, /kdp-wiki, /kdp-chat
skills/kdp-formatting/      the skill: interview, KDP lookup table
kdp/                        the pipeline: ingest -> Book IR -> PDF / EPUB -> preflight
kdp/specs/                  every KDP constant, with its citation
kdp/wiki/                   fetch -> build -> graph (+ the trim-size table extractor)
wiki/                       generated, git-ignored: Amazon's content, never committed
example/hamlet.txt          the flagship example
tests/                      pytest; tests/fixtures holds small tracked manuscripts
```

## Working on the wiki

Never hand-edit `wiki/`; it is regenerated. The build is deterministic, so a
rebuild with no code change produces an identical tree. Four behaviours in
`kdp/wiki/` are easy to break without noticing:

- **Two link forms.** The sidebar uses `/help/topic/<ID>` and in-body
  references use `/help?topicId=<ID>`. About 70 topics appear only in the second.
- **Alias IDs.** One article is served under several legacy IDs. Pages are
  grouped by content hash, one canonical ID wins, and the rest become `aliases:`.
- **Section names** come from `.topic-group-title`, which matches KDP's own breadcrumbs.
- **Tables.** KDP builds them from `<td>` only, so the empty header row must be
  replaced rather than deleted, or the table stops parsing. The trim-size,
  margin and royalty specifications *are* tables.

## Commits

Imperative subject line, with a body that explains *why*. Keep generated-content
changes (for example `kdp/specs/trim_sizes.json`) in their own commit.
