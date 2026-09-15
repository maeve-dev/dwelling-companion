#!/usr/bin/env python3
"""Overclaim-phrasing check for the dwelling companion site.

A grep for one wording of an overclaim misses the same claim where it is
phrased differently. This checks the whole CLAIM CLASS: constructions that
imply the fixed 4s-in / 6s-out circle measures, achieves, or was validated as
matching an individual's personal resonant frequency (RF), or that present
synchrony as an unqualified benefit that follows from the design.

The patterns below target those CONSTRUCTIONS, never the bare topic phrase
"resonant frequency". Honest uses of that phrase -- the population-average
default framing, the calibrated-circle page's heart-rate-variability method,
and footnote citations (Lehrer & Gevirtz / the Mayer wave) -- must stay
unflagged, so do not add the bare phrase here.

Run from the repo root:  python3 check_claims.py [path]
    path may be a single .html file or a directory (default: ".").
Exit 0 if clean, 1 if any overclaim phrasing found.
"""
import sys
from pathlib import Path

# The overclaim phrasing class, case-insensitive. Keep this list auditable and
# explicit: every entry is a construction, not a topic word.
PATTERNS = [
    "scaffolds the resonant frequency",
    "calibrated to the resonant frequency",
    "lands exactly at the resonant frequency",
    "chosen intuitively",
    "chosen by feel",
    "before any research was consulted",
    "confirmed by the research",
    "invites interbrain synchrony",
    "coherence states can couple",
]


def html_files(root):
    """Return the .html files to scan for a file or directory target."""
    p = Path(root)
    if p.is_file():
        return [p] if p.suffix.lower() == ".html" else []
    return sorted(q for q in p.rglob("*.html") if ".git" not in q.parts)


def main(argv):
    target = argv[1] if len(argv) > 1 else "."
    files = html_files(target)
    hits = []
    for f in files:
        text = f.read_text(errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for pat in PATTERNS:
                if pat in low:
                    hits.append(f"{f}:{lineno}: {pat}")
    for h in hits:
        print(h)
    print(f"files scanned: {len(files)}  hits found: {len(hits)}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
