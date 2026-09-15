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
  3. UNPARSEABLE -- a reference with a year but no recognisable author.
  4. NO AUTHOR -- the author slot is empty, is a journal / preprint-server name
     rather than a person, or the reference begins with a title and only then
     gives a parenthesised year.

What counts as a reference:

  * any element whose ``class`` list contains the token ``ref``;
  * when such an element has descendants with class token ``ref-item``, each
    ``ref-item`` is one reference and the container is *not* counted again;
  * a candidate with no ``(19|20)dd`` year is not a reference at all -- that is
    what excludes a bare ``<strong>References</strong>`` heading.

Title extraction does not require ``<em>``.  The title is the text after the
``(dddd)`` / ``(dddd).`` up to whichever comes first: the first ``<em>`` tag, or
the first sentence boundary.  A reference whose *leading* text before the year
is a title rather than an author list is flagged, and that leading text is
recorded as the title so the reference is not also reported as title-less.

Coverage is reported explicitly, and always.  The ``COVERAGE:`` line separates
references found from references that carry a title and references that do not,
plus references the parser could not classify.  No number silently omits what
failed to match: a regex miss shows up as a coverage gap, not as a clean report.

Run from a repo root::

    python3 check_citations.py              # check "." (non-strict)
    python3 check_citations.py src          # check a subdirectory
    python3 check_citations.py src --strict
    python3 check_citations.py . --emit-baseline

``--strict`` exits 1 for ANY finding.  Non-strict exits 0 only when every
finding's location is listed in ``citation_known_issues.txt`` (repo root); a
finding that is not listed there still fails the build.
"""
import argparse
import datetime
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

NOW_YEAR = datetime.date.today().year
BASELINE_NAME = "citation_known_issues.txt"

# Journals / preprint servers that must never occupy the author position.
# Matched against the *first token* of an author slot, case-insensitively.
VENUE_WORDS = (
    "frontiers",
    "scientific",
    "nature",
    "psychophysiology",
    "biorxiv",
    "medrxiv",
    "plos",
    "journal",
    "proceedings",
    "cell",
    "science",
    "brain",
    "neuroimage",
    "cortex",
    "mindfulness",
    "emotion",
)
# Multi-word venue prefixes.  Kept so the first-token rule above does not drop
# any venue the earlier version of this check already caught.
VENUE_PHRASES = ("scientific reports", "plos one", "preprint")

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
# A parenthesised year in the plausible range, with an optional disambiguating
# letter ("2023a").
YEAR = re.compile(r'\(((?:19|20)\d{2}[a-z]?)\)')
SURNAME = re.compile(r"^\s*([A-Z][A-Za-z\u00C0-\u024F'-]+)")
# Title after "(yyyy)" or "(yyyy)." -- up to the first <em> or the first
# sentence boundary: [.?!] + whitespace + capital letter, or end of string.
TITLE_AFTER_YEAR = re.compile(
    r'\(\d{4}[a-z]?\)\.?\s*(.*?)(?=<em\b|[.?!](?:\s+[A-Z])|\s*$)',
    re.S,
)
# Name initials ("J.", "R. E.") -- a strong signal that a slot is an author
# list rather than prose.
INITIALS = re.compile(r"(?<![A-Za-z])[A-Z]\.")

# Words that do not count as prose when deciding whether a slot is a title.
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


def _looks_like_author_slot(slot):
    """True when a slot reads like a list of people, not like prose."""
    s = slot.strip()
    if not s:
        return False
    if "&" in s:
        return True
    if re.search(r"\bet\s+al\b", s, re.I):
        return True
    if INITIALS.search(s):
        return True
    if re.match(r"^[A-Z][A-Za-z\u00C0-\u024F'\-]+\s*,", s):
        return True
    return False


def _looks_like_title(slot):
    """True when a slot reads like the title of a work rather than a name list."""
    s = slot.strip()
    if not s or _looks_like_author_slot(s):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", s)
    if len(words) < 2:
        return False
    lower = [w for w in words if w.islower() and w not in LOWERCASE_STOPWORDS]
    if len(lower) >= 3:
        return True
    # A short, capitalised title that still ends like a sentence ("Being No
    # One.") counts too; a lone surname does not.
    return s.endswith(".") and len(words) >= 3


def _segments(raw):
    """Split a reference into citation segments (``;`` lists and ``),`` lists)."""
    return [seg for seg in re.split(r";\s*|\)\s*,\s*", raw) if seg.strip()]


def no_author(ref):
    """Return a reason string if *ref* has no real author, else None."""
    leading = ref.get("leading") or ""
    if leading and _venue_slot(leading):
        return ("author position holds a journal/preprint name "
                f"({leading!r})")
    if leading and _looks_like_title(leading):
        return "reference begins with a title and gives the year afterwards"

    segments = _segments(ref["raw"]) or [ref["raw"]]
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
    return None


# --- discovery ------------------------------------------------------------

def collect(root):
    """Return ``(refs, source_counts, not_refs, pages)`` for *root*.

    Each ref is a dict with page (relative posix path), line, raw, surname,
    year, venue, locator, title, leading and kind.
    """
    pages = sorted(p for p in Path(root).rglob("*.html") if ".git" not in p.parts)
    refs = []
    source_counts = defaultdict(int)
    not_refs = 0

    for page in pages:
        text = page.read_text(errors="replace")
        rel = page.relative_to(Path(root)).as_posix()

        items = []       # (start, content) for elements with class token ref-item
        containers = []  # (start, end, content) for elements with class token ref
        for tag, attrs, content, start, cstart in iter_elements(text):
            cls = classes_of(attrs)
            if "ref-item" in cls:
                items.append((start, content))
            elif "ref" in cls:
                containers.append((start, cstart + len(content), content))

        emitted = [(start, content, "ref-item") for start, content in items]
        item_starts = [s for s, _ in items]
        for start, end, content in containers:
            # A container whose children are the real references: the children
            # are emitted on their own, so the container is not counted again.
            if any(start <= s < end for s in item_starts):
                continue
            emitted.append((start, content, "ref"))
        emitted.sort()

        for start, content, kind in emitted:
            raw = clean(content)
            if not raw:
                not_refs += 1
                continue
            ym = YEAR.search(raw)
            if not ym:
                # No publication year: not a reference (e.g. the bare
                # <strong>References</strong> heading).
                not_refs += 1
                continue
            lineno = text[:start].count("\n") + 1

            sm = SURNAME.match(raw) or re.match(
                r"\s*([A-Za-z][A-Za-z\u00C0-\u024F'-]+)", raw)

            im = ITALIC.search(content)
            venue = clean(im.group(1)) if im else None
            locator = None
            vm = re.search(r"</em>\s*,\s*([^,]+?)(?:,\s*([0-9]+[^.]*?))?\.\s*$",
                           content, re.I | re.S)
            if vm and vm.group(2):
                locator = clean(vm.group(2))

            leading = clean(raw[: ym.start()])
            if leading and _looks_like_title(leading):
                # Title-before-year shape: the leading text is the title.
                title = leading
            else:
                tm = TITLE_AFTER_YEAR.search(content)
                title = clean(tm.group(1)) if tm else ""
            if not title.strip():
                title = None

            refs.append({
                "page": rel,
                "line": lineno,
                "raw": raw,
                "surname": sm.group(1) if sm else None,
                "year": ym.group(1),
                "venue": venue,
                "locator": locator,
                "title": title,
                "leading": leading,
                "kind": kind,
                "source": content,
            })
            source_counts[kind] += 1

    return refs, dict(source_counts), not_refs, len(pages)


# --- checks ---------------------------------------------------------------

def analyze(refs, now_year=NOW_YEAR):
    findings = []
    groups = defaultdict(list)
    excluded = {"no author": 0, "no title": 0}

    for ref in refs:
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
        if int(r["year"][:4]) > now_year:
            findings.append({
                "check": "FUTURE YEAR",
                "loc": f"{r['page']}:{r['line']}",
                "message": (f"cites ({r['year']}) but the current year is "
                            f"{now_year}: {r['raw'][:110]}"),
            })

    # 3. refs with no recognisable author
    for r in refs:
        if not r["surname"]:
            findings.append({
                "check": "UNPARSEABLE",
                "loc": f"{r['page']}:{r['line']}",
                "message": f"no author found: {r['raw'][:110]}",
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

    return findings, groups, excluded


def coverage(result):
    """The falsifiable coverage summary; printed on every run."""
    refs = result["refs"]
    total = len(refs)
    with_title = sum(1 for r in refs if r["title"])
    unparsed = sum(1 for r in refs if not r["surname"])
    return (f"COVERAGE: refs_total={total} refs_with_title={with_title} "
            f"refs_no_title={total - with_title} refs_unparsed={unparsed}")


# --- baseline -------------------------------------------------------------

def baseline_path():
    return Path(__file__).resolve().parent / BASELINE_NAME


def load_baseline(path):
    """Parse a ``path:line`` baseline; ``#`` comments and blank lines ignored."""
    known = set()
    p = Path(path)
    if not p.exists():
        return known
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?P<path>.+?):(?P<line>\d+)(?:\s+.*)?$", line)
        if m:
            known.add(f"{m.group('path')}:{m.group('line')}")
    return known


def finding_key(f):
    return f["loc"]


def emit_baseline(findings, path=None):
    """Write the current finding locations to *path* and return how many.

    Entries are bare ``path:line`` locations; one ``#`` comment per finding
    records what the defect actually is, so the file can be read (and burned
    down) without re-running the checker.
    """
    known = sorted({finding_key(f) for f in findings})
    by_loc = {}
    for f in findings:
        by_loc.setdefault(finding_key(f), f)
    p = Path(path) if path else baseline_path()
    today = datetime.date.today().isoformat()
    lines = [
        f"# {BASELINE_NAME} -- baseline for check_citations.py",
        f"# Regenerated: {today} by `python3 check_citations.py . --emit-baseline`",
        "#",
        "# THIS IS A BURN-DOWN LIST, NOT A PERMISSION SLIP.",
        "#",
        "# One `<file>:<line>` entry per finding -- the location of the",
        "# reference element (`<p class=\"ref\">` or `<div class=\"ref-item\">`).",
        "# Blank lines and `#` comments are ignored.",
        "#",
        "# These are the malformed citations that already exist on the tree.",
        "# They are listed only so that the NON-STRICT CI run does not fail on",
        "# pre-existing debt while the debt is worked down.  It is not a licence",
        "# to add more:",
        "#",
        "#   * `check_citations.py --strict` fails on ANY finding, listed or not.",
        "#   * the non-strict run fails on any finding NOT listed below, so a NEW",
        "#     violation still fails the build.",
        "#",
        "# When one of these is fixed, delete its line.  Do not add a line to",
        "# make a new failure pass -- fix the citation instead.",
        "#",
    ]
    if known:
        lines.append("# Known findings (what each baselined location is):")
        for loc in known:
            f = by_loc[loc]
            message = " ".join(f["message"].split())
            lines.append(f"#   {loc}  [{f['check']}] {message[:140]}")
        lines.append("#")
    lines.extend(known)
    p.write_text("\n".join(lines) + "\n")
    return len(known)


# --- entry point ----------------------------------------------------------

def run_check(root, now_year=NOW_YEAR):
    refs, source_counts, not_refs, num_pages = collect(root)
    findings, groups, excluded = analyze(refs, now_year)
    return {
        "pages": num_pages,
        "refs": refs,
        "source_counts": source_counts,
        "not_refs": not_refs,
        "findings": findings,
        "groups": groups,
        "excluded": excluded,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", nargs="?", default=".",
                    help="directory to scan (default: .)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 for ANY finding, even a baselined one")
    ap.add_argument("--emit-baseline", action="store_true",
                    help=f"write current findings to {BASELINE_NAME} and exit 0")
    args = ap.parse_args(argv)

    result = run_check(args.dir)
    findings = result["findings"]

    if args.emit_baseline:
        path = baseline_path()
        emit_baseline(findings, path)
        print(f"wrote {path} ({len({f['loc'] for f in findings})} locations)")
        print(coverage(result))
        return 0

    counts = result["source_counts"]
    parts = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(
        f"pages={result['pages']} refs={len(result['refs'])} ({parts}; "
        f"not_refs_skipped={result['not_refs']}) "
        f"key_consistency_entered={sum(len(v) for v in result['groups'].values())} "
        f"no_title_excluded={result['excluded']['no title']} "
        f"no_author_excluded={result['excluded']['no author']}"
    )

    known = load_baseline(baseline_path())
    new = [f for f in findings if finding_key(f) not in known]

    if findings:
        print(f"\nFINDINGS ({len(findings)}; "
              f"{len(findings) - len(new)} baselined, {len(new)} new):\n")
        for f in sorted(findings, key=finding_key):
            tag = "BASELINED" if finding_key(f) in known else "NEW"
            print(f"  [{tag}] {f['check']} {f['loc']}\n      {f['message']}\n")
    else:
        print("FINDINGS: none")

    # Always the last line: what the checker could and could not parse.
    print(coverage(result))

    if args.strict:
        return 1 if findings else 0
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
