"""Let the package be run directly: `python -m kdp analyse book.md`.

There is no console script and nothing to install, because installing this
package is what used to break it: an editable install leaves a .pth file in
site-packages, and on a machine syncing its home directory - iCloud, Dropbox -
that file gets the hidden flag, which Python's site module skips. The package
then stops importing while every file is present and correct.

A package at the repository root needs none of that. The directory you run from
is already on sys.path.
"""
import sys

from .cli import main

if __name__ == "__main__":
    # Titles and chapter names are the author's, in any script. Windows writes
    # piped output as cp1252, which garbles an em dash and crashes on an emoji.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    sys.exit(main())
