#!/usr/bin/env python3
"""Dead-link check for the dwelling companion site.

Checks every .html page for:
  - relative href/src targets that exist on disk
  - in-page anchors (#id) that resolve in the same page
  - cross-page anchors (page.html#id) that resolve in the target page
External http(s) links are listed but not fetched.

Run from the repo root:  python3 check_links.py
Exit 0 if clean, 1 if any dead link.
"""
import re, sys, html
from pathlib import Path

ATTR = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"', re.I)
ID = re.compile(r'\bid\s*=\s*"([^"]+)"', re.I)
NAME = re.compile(r'<a[^>]+\bname\s*=\s*"([^"]+)"', re.I)

pages = sorted(p for p in Path(".").rglob("*.html") if ".git" not in p.parts)
ids = {p: set(ID.findall(p.read_text(errors="replace"))) |
          set(NAME.findall(p.read_text(errors="replace"))) for p in pages}

dead, ext, checked = [], [], 0
for p in pages:
    for raw in ATTR.findall(p.read_text(errors="replace")):
        tgt = html.unescape(raw).strip()
        if not tgt or tgt.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        if tgt.startswith(("http://", "https://", "//")):
            ext.append((p, tgt)); continue
        checked += 1
        if tgt.startswith("#"):
            if tgt[1:] and tgt[1:] not in ids[p]:
                dead.append((p, tgt, "same-page anchor missing"))
            continue
        path_part, _, frag = tgt.partition("#")
        resolved = (p.parent / path_part).resolve()
        if not resolved.exists():
            dead.append((p, tgt, f"missing file: {path_part}"))
        elif frag and resolved.suffix == ".html":
            try:
                rel = Path(resolved.relative_to(Path.cwd().resolve()))
            except ValueError:
                continue
            if frag not in ids.get(rel, set()):
                dead.append((p, tgt, f"anchor #{frag} not in {path_part}"))

print(f"pages={len(pages)} internal_checked={checked} external={len(ext)}")
if dead:
    print(f"\nDEAD ({len(dead)}):")
    for p, t, why in dead:
        print(f"  {p}: {t} -> {why}")
else:
    print("DEAD: none")
sys.exit(1 if dead else 0)
