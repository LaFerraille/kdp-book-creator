# kdp-book-creator

Claude Code plugin (and skills.sh skill) that formats a finished manuscript into
upload-ready KDP paperback, hardcover and ebook files. **Formatting only**: never
write, edit or suggest the author's text, titles or blurbs included.

## Environment

Python 3.11. There is no build system and nothing to install from this repo:
`kdp` is a package at the root, so Python finds it by being run from here.

```bash
uv venv                                       # once
uv pip install -r requirements-dev.txt        # runtime + tests + lint + graph PNG
python -m kdp doctor                          # check the toolchain
python -m kdp wiki build                      # the local KDP wiki (git-ignored)
ruff check . && python -m pytest
```

`bin/kdp` is what plugin users run: Claude Code puts `bin/` on PATH, and the
script creates `.venv` on first use and sets `KDP_BUILD_DIR=$PWD/build`.

Do not `pip install` into conda base, and do not add a `pyproject.toml`: an
editable install leaves a `.pth` in site-packages, and on a machine syncing its
home directory that file gets the hidden flag, which Python's `site` module
skips. The package then stops importing while every file is present. The same
sync can corrupt `.venv`; if imports fail oddly, recreate it.

Dependencies belong in `requirements.txt` (runtime) or `requirements-dev.txt`.

## Never guess a KDP rule — look it up

KDP rejects files over specifics and changes them without notice. `wiki/` is a
local mirror of the KDP Help Center, built by `python -m kdp wiki build` and
never committed (it is Amazon's content).

1. `python -m kdp wiki search "<question>"` ranks topics, with their graph neighbours.
2. Open the *one* topic that answers it (`wiki/topics/<slug>.md`). Never read
   the corpus wholesale; it is about 2 MB.
3. `wiki/INDEX.md` is the full arborescence; `wiki/index.json` maps any of the
   335 known topic IDs (legacy aliases included) to its file.

## Layout

```
bin/kdp                 launcher on PATH for plugin users
commands/*.md           /kdp-book /kdp-cover /kdp-check /kdp-wiki /kdp-chat
skills/kdp-formatting/  SKILL.md + references (interview, lookup table)
kdp/                    pipeline: ingest -> IR -> render_print / render_epub -> preflight
kdp/specs/              every KDP constant, cited; trim_sizes.json is generated
kdp/wiki/               fetch.py -> build.py -> graph.py; specs.py regenerates trim_sizes.json
wiki/                   generated, git-ignored: .cache/ topics/ INDEX.md index.json graph.json
example/hamlet.txt      flagship example (Folger, CC BY-NC 3.0); docs/ holds its session + images
.claude-plugin/         plugin.json + marketplace.json (the repo is its own marketplace)
```

## Working on the wiki code

Never hand-edit `wiki/`. The build is deterministic: a rebuild with no code
change produces an identical tree. Four non-obvious things `kdp/wiki/` handles;
preserve them if you refactor:

- **Two link forms.** Sidebar uses `/help/topic/<ID>`, in-body cross references
  use `/help?topicId=<ID>`. About 70 topics appear *only* in the second form.
- **Alias IDs.** The same article is served under several legacy IDs. Pages are
  grouped by content hash; one canonical ID wins, the rest go to `aliases:`.
- **Section names.** Level-0 nav anchors inherit their first child's label; the
  real names come from `.topic-group-title` (matches KDP's own breadcrumbs).
- **Tables.** KDP builds them from `<td>` only, so the converter emits an empty
  header row that must be replaced, not just deleted, or the table stops
  parsing. The trim-size, margin, and royalty specs *are* tables.

`kdp wiki build` also regenerates `kdp/specs/trim_sizes.json` and says if it
changed; that diff means KDP changed a table and needs a human look.

## Conventions

- Commits: imperative subject, body explains *why*. Keep generated-content
  changes (trim_sizes.json, docs/images) in their own commit.
- Tests that need the wiki skip when it is absent; `.github/workflows/kdp-drift.yml`
  rebuilds it weekly and fails when a cited constant disappears.
