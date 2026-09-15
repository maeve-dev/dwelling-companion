#!/usr/bin/env python3
"""Citation-consistency check for the dwelling companion site.

A link checker cannot find a wrong citation: the references on these pages are
prose in <p class="ref">, with no href to follow. This checks the thing that is
actually checkable -- that the same work is cited the same way everywhere, and
that no citation claims a publication year that has not happened yet.

Checks:
  1. KEY CONSISTENCY -- the same (first-author surname, year) must carry the
     same venue and the same volume/pages wherever it appears.
  2. FUTURE YEAR -- a cited publication year later than the current year.
  3. ORPHAN REFS -- a <p class="ref"> with no recognisable author-year.

Run from the repo root:  python3 check_citations.py
Exit 0 if clean, 1 if any finding.
"""
import re, sys, html, datetime
from pathlib import Path
from collections import defaultdict

REF = re.compile(r'<p\s+class="ref"[^>]*>(.*?)</p>', re.I | re.S)
TAG = re.compile(r'<[^>]+>')
# "Surname, A., & Other, B. (2023). Title. *Venue*, 13, 31494."
YEAR = re.compile(r'\((\d{4}[a-z]?)\)')
SURNAME = re.compile(r'^\s*([A-Z][A-Za-z\u00C0-\u024F\'-]+)')
VENUE = re.compile(r'</em>\s*,\s*([^,]+?)(?:,\s*([0-9]+[^.]*?))?\.\s*$')
ITALIC = re.compile(r'<em>(.*?)</em>', re.I | re.S)

NOW_YEAR = datetime.date.today().year

pages = sorted(p for p in Path(".").rglob("*.html") if ".git" not in p.parts)
refs = []          # (page, lineno, raw_text, surname, year, venue, locator)
for p in pages:
    text = p.read_text(errors="replace")
    for m in REF.finditer(text):
        raw = html.unescape(TAG.sub("", m.group(1))).strip()
        raw = re.sub(r"\s+", " ", raw)
        if not raw:
            continue
        lineno = text[: m.start()].count("\n") + 1
        sm = SURNAME.match(raw)
        ym = YEAR.search(raw)
        if sm is None:
            sm = re.match(r"\s*([A-Za-z][A-Za-z\u00C0-\u024F'-]+)", raw)
        venue = None
        im = ITALIC.search(m.group(1))
        if im:
            venue = html.unescape(TAG.sub("", im.group(1))).strip()
        locator = None
        vm = VENUE.search(raw)
        if vm and vm.group(2):
            locator = re.sub(r"\s+", " ", vm.group(2)).strip()
        tm = re.search(r"\(\d{4}[a-z]?\)\.\s*(.+?)\.\s*<em>", m.group(1), re.S)
        title = re.sub(r"\s+", " ", html.unescape(TAG.sub("", tm.group(1)))).strip() if tm else None
        refs.append((p, lineno, raw, sm.group(1) if sm else None,
                     ym.group(1) if ym else None, venue, locator, title))

findings = []

# 1. same (surname, year) must agree on venue and locator
groups = defaultdict(list)
for r in refs:
    if r[7]:
        groups[(r[3] or '?', r[4] or '?', r[7][:60].lower())].append(r)

for (surname, year, _title), rs in sorted(groups.items()):
    venues = {r[5] for r in rs if r[5]}
    locators = {r[6] for r in rs if r[6]}
    if len(venues) > 1:
        findings.append(
            f"VENUE DISAGREEMENT  {surname} ({year}) cited in "
            f"{len(venues)} different venues:\n"
            + "\n".join(f"      {v}\n        {r[0]}:{r[1]}" for v in sorted(venues)
                        for r in rs if r[5] == v))
    if len(locators) > 1:
        findings.append(
            f"LOCATOR DISAGREEMENT  {surname} ({year}) cited with "
            f"{len(locators)} different volume/page strings:\n"
            + "\n".join(f"      {l!r}\n        {r[0]}:{r[1]}" for l in sorted(locators)
                        for r in rs if r[6] == l))

# 2. future publication years
for r in refs:
    if r[4] and r[4][:4].isdigit() and int(r[4][:4]) > NOW_YEAR:
        findings.append(f"FUTURE YEAR  {r[0]}:{r[1]}  cites ({r[4]}) "
                        f"but the current year is {NOW_YEAR}\n      {r[2][:110]}")

# 3. refs with no recognisable author-year
for r in refs:
    if not r[3] or not r[4]:
        findings.append(f"UNPARSEABLE  {r[0]}:{r[1]}  no author-year found\n"
                        f"      {r[2][:110]}")

print(f"pages={len(pages)} refs={len(refs)} distinct_works={len(groups)}")
if findings:
    print(f"\nFINDINGS ({len(findings)}):\n")
    for f in findings:
        print(f"  {f}\n")
else:
    print("FINDINGS: none")
sys.exit(1 if findings else 0)
