---
description: Preflight a PDF against KDP's requirements before uploading
argument-hint: <file.pdf>
---

Preflight `$1` against KDP's requirements.

Run `kdp check $1 --spec build/book.yaml` (drop `--spec` if there is
no book.yaml, and say which trim size you assumed).

Report every check. For each failure, give the fix, and cite the KDP topic it
comes from using the `kdp-formatting` skill's lookup table. Do not call a file
ready to upload unless every error-level check passed.
