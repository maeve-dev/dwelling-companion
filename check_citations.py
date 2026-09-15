#!/usr/bin/env python3
"""Citation-consistency check for the dwelling companion site.

A link checker cannot find a wrong citation: the references on these pages are
prose in ``class="ref"`` containers, with no href to follow.  This checks the
thing that is actually checkable -- that the same work is cited the same way
everywhere, that no citation claims a publication year that has not happened
yet, and that every reference actually names an author.

Checks:
  1. KEY CONSISTENCY -- the same (first-author surname, year, title) must carry
     the same venue and the same volume/pages wherever it appears.
  2. FUTURE YEAR -- a cited publication year later than the current year.
  3. UNPARSEABLE -- a reference with no recognisable author-year.
  4. NO AUTHOR -- the author slot is empty, is a journal / preprint-server name
     rather than a person, or the reference begins with a title and only then
     gives a parenthesised year.

Coverage is reported explicitly.  The summary line separates refs found from
refs the key-consistency comparison could not use and *why*, plus refs the
parser could not classify at all.  No number silently omits what failed to
match: a regex miss must show up as a coverage gap, not as a clean report.

Run from a repo root::

    python3 check_citations.py            # check "." (non-strict)
    python3 check_citations.py src        # check a subdirectory
    python3 check_citations.py src --strict

``--strict`` exits 1 for ANY finding.  Non-strict exits 0 only when every
finding is listed in ``citation_known_issues.txt``; a finding that is not in
that baseline still fails the build.
"""
import argparse
import datetime
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

NOW_YEAR = datetime.date.today().year

# --- markup parsing -------------------------------------------------------

VOID = {"br", "img", "hr", "meta", "link", "input", "area", "base",
        "col", "embed", "source", "track", "wbr"}

# One HTML tag, tolerating quoted attribute values that contain '>'.
TOKEN = re.compile(
    r'<(/?)([A-Za-z][A-Za-z0-9]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*)\s*(/?)>',
    re.S,
)
CLASS_ATTR = re.compile(r'class\s*=\s*"([^"]*)"', re.I)
TAG = re.compile(r'<[^>]+>')
ITALIC = re.compile(r'<em[^>]*>(.*?)</em>', re.I | re.S)
YEAR = re.compile(r'\((\d{4}[a-z]?)\)')
SURNAME = re.compile(r"^\s*([A-Z][A-Za-z\u00C0-\u024F'-]+)")
# Title after "(yyyy).": up to the first <em> OR the next sentence boundary.
TITLE_HTML = re.compile(
    r'\(\d{4}[a-z]?\)\.\s*(.*?)(?=<em\b|[.?!](?:\s+[A-Z]|\s*$))',
    re.S,
)

# Journals / preprint servers that must never occupy the author position.
VENUE_WORDS = {
    "nature", "scientific", "frontiers", "psychophysiology", "plos",
    "biorxiv", "medrxiv", "elife", "preprints",
}
VENUE_PHRASES = ("scientific reports", "plos one", "preprint")

# Words that do not count as prose when deciding whether an author slot is
# really a title.
LOWERCASE_STOPWORDS = {
    "and", "or", "the", "of", "in", "to", "for", "on", "a", "an", "at", "by",
    "et", "al", "de", "van", "von", "del", "la", "le", "du", "el", "der",
    "den", "with", "from", "as", "is", "are",
}


def classes_of(attrs):
    m = CLASS_ATTR.search(attrs)
    return m.group(1).split() if m else []


def iter_elements(text):
    """Yield ``(tag, attrs, content, start, content_start)`` for every element.

    Handles nesting by tracking open tags in a stack, so a container's content
    span really covers its children.
    """
    stack = []
    for m in TOKEN.finditer(text):
        closing, tag, attrs, selfclose = (
            m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        )
        if tag in VOID or selfclose:
            continue
        if not closing:
            stack.append((tag, attrs, m.end(), m.start()))
        else:
            for j in range(len(stack) - 1, -1, -1):
                if stack[j][0] == tag:
                    t, a, cstart, ostart = stack[j]
                    yield (t, a, text[cstart:m.start()], ostart, cstart)
                    del stack[j:]
                    break


def clean(fragment):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub("", fragment))).strip()


def is_heading(content):
    """True for a section label such as ``<strong>References</strong>``."""
    c = content.strip()
    if not c:
        return True
    m = re.fullmatch(r"<(strong|b|h[1-6]|em)\b[^>]*>(.*?)</\1>", c, re.I | re.S)
    if m:
        label = clean(m.group(2)).lower().rstrip(":")
        if label in {"references", "reference", "bibliography",
                     "works cited", "sources"}:
            return True
    visible = clean(c).lower().rstrip(":")
    if visible in {"references", "reference", "bibliography",
                   "works cited", "sources"}:
        return True
    return False


FOOTNOTE_ID = re.compile(r'\bid="fn[0-9]+"', re.I)


def collect(root):
    """Return ``(refs, source_counts, headings_skipped, pages)`` for *root*.

    Each ref is a dict with page (relative posix path), line, raw, surname,
    year, venue, locator, title.
    """
    pages = sorted(p for p in Path(root).rglob("*.html") if ".git" not in p.parts)
    refs = []
    source_counts = defaultdict(int)
    headings_skipped = 0

    for page in pages:
        text = page.read_text(errors="replace")
        rel = page.relative_to(Path(root)).as_posix()

        items = []       # (start, content)
        containers = []  # (start, end, content)
        footnotes = []   # (start, content)
        for tag, attrs, content, start, cstart in iter_elements(text):
            cls = classes_of(attrs)
            if FOOTNOTE_ID.search(attrs):
                footnotes.append((start, content))
            if "ref-item" in cls:
                items.append((start, content))
            elif "ref" in cls:
                containers.append((start, cstart + len(content), content))

        emitted = []
        item_starts = [s for s, _ in items]
        for start, content in items:
            emitted.append((start, content, "ref-item"))
        for start, content in footnotes:
            emitted.append((start, content, "footnote"))
        for start, end, content in containers:
            # Skip a container whose children are the real references; those
            # children are emitted on their own, so this avoids double-counting.
            if any(start <= s < end for s in item_starts):
                continue
            emitted.append((start, content, "ref"))
        emitted.sort()

        for start, content, kind in emitted:
            if is_heading(content):
                headings_skipped += 1
                continue
            raw = clean(content)
            if kind == "footnote":
                raw = re.sub(r"^[0-9]+\s*", "", raw)
            if not raw:
                headings_skipped += 1
                continue
            lineno = text[:start].count("\n") + 1

            sm = SURNAME.match(raw)
            if sm is None:
                sm = re.match(r"\s*([A-Za-z][A-Za-z\u00C0-\u024F'-]+)", raw)
            ym = YEAR.search(raw)

            im = ITALIC.search(content)
            venue = clean(im.group(1)) if im else None
            locator = None
            vm = re.search(r"</em>\s*,\s*([^,]+?)(?:,\s*([0-9]+[^.]*?))?\.\s*$",
                           content, re.I | re.S)
            if vm and vm.group(2):
                locator = clean(vm.group(2))

            tm = TITLE_HTML.search(content)
            title = clean(tm.group(1)) if tm else None
            if title == "":
                title = None

            refs.append({
                "page": rel,
                "line": lineno,
                "raw": raw,
                "surname": sm.group(1) if sm else None,
                "year": ym.group(1) if ym else None,
                "venue": venue,
                "locator": locator,
                "title": title,
                "kind": kind,
                "source": content,
            })
            source_counts[kind] += 1

    return refs, dict(source_counts), headings_skipped, len(pages)


# --- author-slot analysis -------------------------------------------------

def _venue_slot(slot):
    """Return True if the author slot begins with a journal/preprint name."""
    s = slot.strip().strip(":")
    if not s:
        return True
    low = s.lower()
    for phrase in VENUE_PHRASES:
        if low.startswith(phrase):
            return True
    first = re.split(r"[\s,]+", s, maxsplit=1)[0].strip(".,;:").lower()
    return first in VENUE_WORDS


def _slot_is_title(slot):
    """True if the author slot reads like a title rather than a name list."""
    s = slot.strip()
    if not s:
        return False
    if "&" in s or "," in s:
        return False
    if re.search(r"\bet\s+al\b", s, re.I):
        return False
    if re.search(r"[A-Z]\.", s):  # name initials
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", s)
    lower = [w for w in words if w.islower() and w not in LOWERCASE_STOPWORDS]
    return len(lower) >= 3


def _segments(raw):
    """Split a ref into citation segments (``;`` lists and ``),`` lists)."""
    return [seg for seg in re.split(r";\s*|\)\s*,\s*", raw) if seg.strip()]


def no_author(ref):
    """Return a reason string if *ref* has no real author, else None."""
    segments = _segments(ref["raw"])
    if not segments:
        segments = [ref["raw"]]
    for seg in segments:
        ym = YEAR.search(seg)
        if not ym:
            continue
        slot = seg[: ym.start()]
        if not slot.strip():
            return "author position is empty"
        if _venue_slot(slot):
            return ("author position holds a journal/preprint name "
                    f"({slot.strip()!r})")
        if _slot_is_title(slot):
            return ("reference begins with a title and gives the year "
                    "afterwards")
    return None


# --- checks ---------------------------------------------------------------

def analyze(refs, now_year=NOW_YEAR):
    findings = []
    groups = defaultdict(list)
    excluded = {"no year": 0, "no author": 0, "no title": 0}

    for ref in refs:
        if not ref["year"]:
            excluded["no year"] += 1
            continue
        if not ref["surname"]:
            excluded["no author"] += 1
            continue
        if not ref["title"]:
            excluded["no title"] += 1
            continue
        key = (ref["surname"], ref["year"], ref["title"][:60].lower())
        groups[key].append(ref)

    # 1. same work must agree on venue and locator
    for (surname, year, _title), rs in sorted(groups.items()):
        venues = {r["venue"] for r in rs if r["venue"]}
        locators = {r["locator"] for r in rs if r["locator"]}
        if len(venues) > 1:
            detail = " | ".join(f"{v!r} at {r['page']}:{r['line']}"
                                for r in rs for v in [r["venue"]] if v)
            for r in rs:
                if r["venue"]:
                    findings.append({
                        "check": "VENUE DISAGREEMENT",
                        "loc": f"{r['page']}:{r['line']}",
                        "message": (f"{surname} ({year}) cited in "
                                    f"{len(venues)} venues: {detail}"),
                    })
        if len(locators) > 1:
            detail = " | ".join(f"{l!r} at {r['page']}:{r['line']}"
                                for r in rs for l in [r["locator"]] if l)
            for r in rs:
                if r["locator"]:
                    findings.append({
                        "check": "LOCATOR DISAGREEMENT",
                        "loc": f"{r['page']}:{r['line']}",
                        "message": (f"{surname} ({year}) cited with "
                                    f"{len(locators)} volume/page strings: "
                                    f"{detail}"),
                    })

    # 2. future publication years
    for r in refs:
        if r["year"] and r["year"][:4].isdigit() and int(r["year"][:4]) > now_year:
            findings.append({
                "check": "FUTURE YEAR",
                "loc": f"{r['page']}:{r['line']}",
                "message": (f"cites ({r['year']}) but the current year is "
                            f"{now_year}: {r['raw'][:110]}"),
            })

    # 3. refs with no recognisable author-year
    for r in refs:
        if not r["surname"] or not r["year"]:
            findings.append({
                "check": "UNPARSEABLE",
                "loc": f"{r['page']}:{r['line']}",
                "message": f"no author-year found: {r['raw'][:110]}",
            })

    # 4. refs with no real author
    for r in refs:
        reason = no_author(r)
        if reason:
            findings.append({
                "check": "NO AUTHOR",
                "loc": f"{r['page']}:{r['line']}",
                "message": f"{reason}: {r['raw'][:110]}",
            })

    unclassified = sum(1 for r in refs if not r["surname"] or not r["year"])
    return findings, groups, excluded, unclassified


# --- baseline -------------------------------------------------------------

def baseline_path():
    return Path(__file__).resolve().parent / "citation_known_issues.txt"


def load_baseline(path):
    known = set()
    p = Path(path)
    if not p.exists():
        return known
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?P<loc>.+?):(?P<line>\d+)\s+(?P<check>\S.*?)\s*$", line)
        if m:
            known.add(f"{m.group('loc')}:{m.group('line')} {m.group('check')}")
    return known


def finding_key(f):
    return f"{f['loc']} {f['check']}"


# --- entry point ----------------------------------------------------------

def run_check(root, now_year=NOW_YEAR):
    refs, source_counts, headings_skipped, num_pages = collect(root)
    findings, groups, excluded, unclassified = analyze(refs, now_year)
    return {
        "pages": num_pages,
        "refs": refs,
        "source_counts": source_counts,
        "headings_skipped": headings_skipped,
        "findings": findings,
        "groups": groups,
        "excluded": excluded,
        "unclassified": unclassified,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", nargs="?", default=".", help="directory to scan (default: .)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 for ANY finding, even a baselined one")
    ap.add_argument("--emit-baseline", action="store_true",
                    help="print baseline lines for the current findings and exit 0")
    args = ap.parse_args(argv)

    result = run_check(args.dir)
    findings = result["findings"]
    counts = result["source_counts"]
    excluded = result["excluded"]

    if args.emit_baseline:
        for f in sorted(findings, key=finding_key):
            print(finding_key(f))
        return 0

    parts = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(
        f"pages={result['pages']} refs={len(result['refs'])} ({parts}; "
        f"headings_skipped={result['headings_skipped']}) "
        f"key_consistency_entered={sum(len(v) for v in result['groups'].values())} "
        f"excluded={sum(excluded.values())} "
        f"(no_title={excluded['no title']} no_author={excluded['no author']} "
        f"no_year={excluded['no year']}) "
        f"unclassified={result['unclassified']}"
    )

    known = load_baseline(baseline_path())
    new = [f for f in findings if finding_key(f) not in known]
    baselined = [f for f in findings if finding_key(f) in known]

    if findings:
        print(f"\nFINDINGS ({len(findings)}; "
              f"{len(baselined)} baselined, {len(new)} new):\n")
        for f in sorted(findings, key=finding_key):
            tag = "baselined" if finding_key(f) in known else "NEW"
            print(f"  [{tag}] {f['check']} {f['loc']}\n      {f['message']}\n")
    else:
        print("FINDINGS: none")

    if args.strict:
        return 1 if findings else 0
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
