"""Fetch every Amazon KDP help topic page into a local HTML cache.

The KDP help centre renders its complete navigation tree server-side on every
page, so one page gives us the full arborescence and the closed set of topic
IDs. We crawl from the tree and re-check each fetched page for unseen IDs.
"""
import json
import random
import sys
import time
import urllib.error
import urllib.request

from . import CACHE, TOPIC_RE

ROOT = "https://kdp.amazon.com/en_US/help/"
TOPIC_URL = "https://kdp.amazon.com/en_US/help/topic/{id}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")



def get(url, retries=4):
    """Fetch a page. Returns None for a dead link (KDP cross-references a
    number of topics it has since deleted), raises on anything else."""
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:  # gone for good - retrying will not help
                return None
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt + random.random()
            print(f"    retry {attempt + 1} after {wait:.1f}s (HTTP {e.code})",
                  file=sys.stderr)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt + random.random()
            print(f"    retry {attempt + 1} after {wait:.1f}s ({e})", file=sys.stderr)
            time.sleep(wait)


def topic_ids(html):
    return set(TOPIC_RE.findall(html))


def fetch(refresh=False, delay=0.6):
    """Cache every help page under wiki/.cache. Resumable: pages already
    cached are reused unless `refresh` is set."""
    CACHE.mkdir(parents=True, exist_ok=True)

    print("fetching help centre root ...")
    root_html = get(ROOT)
    (CACHE / "_root.html").write_text(root_html, encoding="utf-8")

    queue = sorted(topic_ids(root_html))
    seen = set(queue)
    print(f"  {len(queue)} topic ids in the navigation tree")

    done = 0
    dead = set()
    while queue:
        tid = queue.pop(0)
        dest = CACHE / f"{tid}.html"
        if dest.exists() and not refresh:
            html = dest.read_text(encoding="utf-8")
        else:
            html = get(TOPIC_URL.format(id=tid))
            time.sleep(delay)
            if html is None:
                dead.add(tid)
                seen.discard(tid)
                print(f"  ! {tid} is a dead link (404), skipping", flush=True)
                continue
            dest.write_text(html, encoding="utf-8")
        done += 1
        new = topic_ids(html) - seen
        if new:
            print(f"  + {len(new)} new topic(s) discovered via {tid}")
            seen |= new
            queue.extend(sorted(new))
        print(f"  [{done}/{len(seen)}] {tid}", file=sys.stderr, flush=True)

    manifest = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "topic_count": len(seen),
        "topic_ids": sorted(seen),
        "dead_ids": sorted(dead),
    }
    (CACHE / "_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\ndone: {len(seen)} topics cached in {CACHE}"
          + (f" ({len(dead)} dead links skipped)" if dead else ""))

