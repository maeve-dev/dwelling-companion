#!/usr/bin/env python3
"""DOI-resolution check for the dwelling companion site.

Every other citation checker in this repo compares the pages to each other.
check_citations.py runs four checks -- venue/locator agreement, future year,
unparseable, and no-author -- and all four are closed-world: a citation that is
wrong in exactly the same way everywhere passes all of them.  The pages cite
DOIs, and nothing in the repo had ever resolved one.  This is that missing
check: each DOI must resolve to the work the page claims it is.

Checks (each finding, never a silent pass):
  1. NOT IN CACHE -- a DOI that appears on a page but has no entry in the
     checked-in ``dois_registry.json``.  This is a coverage gap, and per this
     repo's stated philosophy an unverifiable DOI must show up as a gap, not as
     a clean report.  It is reported, never skipped.
  2. TITLE MISMATCH -- the registry title does not match the title the page
     states for that DOI.
  3. YEAR MISMATCH -- the cited year matches NONE of the year candidates the
     registry records (published-print / issued / published-online).  Crossref's
     ``issued`` is frequently the online-first date, so a citation whose printed
     issue is a later year still matches against ``published-print``.
  4. LOCATOR MISMATCH -- volume / issue / pages disagree between the registry
     and the page, where the page states them.

What this checker CANNOT see:

  * It reads only the checked-in cache, never the network.  The cache is a
    snapshot; a stale cache is a fresh risk that nothing yet schedules.  Only
    ``--refresh`` touches Crossref, and it is run by hand.
  * It cannot tell that a DOI resolves to a *retracted* or replaced record, only
    that the bibliographic metadata Crossref reports does not match the page.
  * It cannot compare a field the page does not state: a volume the page omits
    is skipped, not inferred.  A field Crossref itself omits is likewise
    skipped for that comparison (still counted as verified for the others).
  * A DOI written on a page after the sentence that names it still needs the
    title and locator on the same line to be parsed; the check reports what it
    can and lets the coverage line name the rest.

Run from a repo root::

    python3 check_dois.py                 # check "." against the checked-in cache
    python3 check_dois.py src             # check a subdirectory
    python3 check_dois.py src --strict    # exit 1 for ANY finding
    python3 check_dois.py . --refresh     # re-fetch the cache from Crossref

``--strict`` exits 1 for ANY finding.  Non-strict exits 0 only when every
finding is listed in ``doi_known_issues.txt`` (which does not need to exist); a
finding that is not in that baseline still fails the build.  The summary line
separates DOI occurrences FOUND from occurrences actually VERIFIED against the
cache.
"""
import argparse
import datetime
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

# --- extraction -----------------------------------------------------------

# A DOI is 10.<registrant>/<suffix>; stop at whitespace or markup delimiters.
DOI_RE = re.compile(r'10\.\d{4,9}/[^\s"\'<>()]+')

# The published title sits between "(yyyy)." and the venue <em> (or the next
# sentence boundary).  Same shape check_citations.py uses, kept here so the two
# checkers stay independently runnable.
TITLE_HTML = re.compile(
    r'\(\d{4}[a-z]?\)\.\s*(.*?)(?=<em\b|[.?!](?:\s+[A-Z]|\s*$))',
    re.S,
)
ITALIC = re.compile(r'<em[^>]*>(.*?)</em>', re.I | re.S)
LOCATOR = re.compile(r'</em>\s*,\s*([^.<]*)')
YEAR = re.compile(r'\((\d{4})[a-z]?\)')
TAG = re.compile(r'<[^>]+>')

USER_AGENT = ("dwelling-companion-doi-check/1.0 "
              "(https://github.com/maeve-dev/dwelling-companion)")

YEAR_FIELDS = ("published-print", "issued", "published-online")


def clean(fragment):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub("", fragment))).strip()


def collect_dois(root):
    """Return one record per DOI occurrence: page, line, doi, text.

    ``text`` is the enclosing line, which is where the title and locator the
    page states for the DOI live.
    """
    pages = sorted(p for p in Path(root).rglob("*.html") if ".git" not in p.parts)
    occurrences = []
    for page in pages:
        text = page.read_text(errors="replace")
        rel = page.relative_to(Path(root)).as_posix()
        lines = text.splitlines()
        for m in DOI_RE.finditer(text):
            doi = m.group(0).rstrip(".,;")
            lineno = text[:m.start()].count("\n") + 1
            occurrences.append({
                "page": rel,
                "line": lineno,
                "doi": doi,
                "text": lines[lineno - 1] if lineno - 1 < len(lines) else "",
            })
    return occurrences, len(pages)


def parse_citation(text):
    """Pull the fields the page states for the DOI out of one line."""
    fields = {"year": None, "title": None, "container": None,
              "volume": None, "issue": None, "page": None}
    ym = YEAR.search(text)
    if ym:
        fields["year"] = ym.group(1)

    tm = TITLE_HTML.search(text)
    if tm:
        title = clean(tm.group(1))
        fields["title"] = title or None

    im = ITALIC.search(text)
    if im:
        fields["container"] = clean(im.group(1)) or None

    lm = LOCATOR.search(text)
    if lm:
        loc = clean(lm.group(1))
        parts = [p.strip() for p in loc.split(",")]
        if parts:
            vm = re.match(r'^(\d+)\s*(?:\(([^)]+)\))?$', parts[0])
            if vm:
                fields["volume"] = vm.group(1)
                fields["issue"] = vm.group(2)
            if len(parts) > 1 and parts[1]:
                fields["page"] = parts[1]
    return fields


# --- comparison -----------------------------------------------------------

def normalize(text):
    """Lowercase, unescape, collapse whitespace, strip punctuation/dashes."""
    if text is None:
        return ""
    text = html.unescape(text).lower()
    text = re.sub(r"[\u2013\u2014\u2010-\u2015]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_page(text):
    """Normalize a page/locator string for comparison (dashes -> hyphen)."""
    if text is None:
        return ""
    text = html.unescape(text).lower()
    text = re.sub(r"[\u2013\u2014\u2010-\u2015]", "-", text)
    return re.sub(r"\s+", "", text)


def titles_agree(page_title, registry_title):
    """Tolerant prefix/containment test.

    Page titles are sometimes cut short by markup, so an exact match is too
    strict.  Returns False only when neither normalized title contains the
    other.
    """
    a = normalize(page_title)
    b = normalize(registry_title)
    if not a or not b:
        return None
    return a == b or a.startswith(b) or b.startswith(a) or a in b or b in a


def year_candidates(record):
    years = record.get("years") or {}
    return {k: v for k, v in years.items() if v}


def compare(occurrence, record):
    """Return ``(findings, matched_candidate)`` for one cache-backed occurrence."""
    fields = parse_citation(occurrence["text"])
    loc = f'{occurrence["page"]}:{occurrence["line"]}'
    findings = []
    matched = None

    page_title = fields["title"]
    if page_title is None:
        findings.append({
            "check": "TITLE NOT STATED",
            "loc": loc,
            "message": (f"{occurrence['doi']} is cached but the page states "
                        f"no title for it, so the resolution cannot be "
                        f"checked: {occurrence['text'].strip()[:110]}"),
        })
    elif titles_agree(page_title, record.get("title")) is False:
        findings.append({
            "check": "TITLE MISMATCH",
            "loc": loc,
            "message": (f"{occurrence['doi']} page states {page_title!r} but "
                        f"the registry title is {record.get('title')!r}"),
        })

    candidates = year_candidates(record)
    if fields["year"]:
        hit = [field for field in YEAR_FIELDS
               if candidates.get(field) == fields["year"]]
        if hit:
            matched = hit[0]
        else:
            findings.append({
                "check": "YEAR MISMATCH",
                "loc": loc,
                "message": (f"{occurrence['doi']} is cited as "
                            f"({fields['year']}) but the registry candidates "
                            f"are {candidates or '{}'}"),
            })

    diffs = []
    if fields["volume"] and record.get("volume"):
        if str(fields["volume"]).strip() != str(record["volume"]).strip():
            diffs.append(f"volume page={fields['volume']!r} "
                         f"registry={record['volume']!r}")
    if fields["issue"] and record.get("issue"):
        if str(fields["issue"]).strip() != str(record["issue"]).strip():
            diffs.append(f"issue page={fields['issue']!r} "
                         f"registry={record['issue']!r}")
    if fields["page"] and record.get("page"):
        if normalize_page(fields["page"]) != normalize_page(record["page"]):
            diffs.append(f"page page={fields['page']!r} "
                         f"registry={record['page']!r}")
    if diffs:
        findings.append({
            "check": "LOCATOR MISMATCH",
            "loc": loc,
            "message": f"{occurrence['doi']}: " + "; ".join(diffs),
        })

    return findings, matched


# --- cache ----------------------------------------------------------------

def default_registry_path():
    return Path(__file__).resolve().parent / "dois_registry.json"


def load_registry(path):
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(errors="replace"))
    return {k: v for k, v in data.items()
            if k != "fetched_at" and isinstance(v, dict)}


def fetch(doi):
    """Resolve one DOI against Crossref and return the cached record shape."""
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as response:
        message = json.load(response)["message"]

    def first(value):
        return value[0] if isinstance(value, list) and value else None

    def year_of(field):
        block = message.get(field)
        if not block:
            return None
        parts = block.get("date-parts") or []
        if parts and parts[0]:
            return str(parts[0][0])
        return None

    return {
        "title": first(message.get("title")),
        "container": first(message.get("container-title")),
        "volume": message.get("volume"),
        "issue": message.get("issue"),
        "page": message.get("page"),
        "years": {field: year_of(field) for field in YEAR_FIELDS},
    }


def refresh(root, registry_path):
    occurrences, _ = collect_dois(root)
    dois = sorted({o["doi"] for o in occurrences})
    works = {}
    for doi in dois:
        try:
            works[doi] = fetch(doi)
        except Exception as exc:  # noqa: BLE001 - report, never write a hole
            print(f"could not resolve {doi}: {type(exc).__name__}: {exc}")
            print("refusing to write a cache with a missing record")
            return 1
        print(f"resolved {doi}")
    payload = {"fetched_at": datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    payload.update(works)
    registry_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(works)} DOI records to {registry_path} "
          f"(fetched_at={payload['fetched_at']})")
    return 0


# --- baseline -------------------------------------------------------------

def baseline_path():
    return Path(__file__).resolve().parent / "doi_known_issues.txt"


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

def run_check(root, registry_path):
    occurrences, pages = collect_dois(root)
    registry = load_registry(registry_path)
    findings = []
    matched_by = Counter()
    verified = 0
    for occurrence in occurrences:
        record = registry.get(occurrence["doi"])
        if record is None:
            findings.append({
                "check": "DOI NOT IN CACHE",
                "loc": f'{occurrence["page"]}:{occurrence["line"]}',
                "message": (f"{occurrence['doi']} appears on the page but has "
                            f"no entry in {Path(registry_path).name}: it cannot "
                            f"be verified offline and must not pass silently"),
            })
            continue
        verified += 1
        found, matched = compare(occurrence, record)
        findings.extend(found)
        if matched:
            matched_by[matched] += 1
    return {
        "pages": pages,
        "occurrences": occurrences,
        "distinct": len({o["doi"] for o in occurrences}),
        "verified": verified,
        "findings": findings,
        "matched_by": matched_by,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", nargs="?", default=".", help="directory to scan (default: .)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 for ANY finding, even a baselined one")
    ap.add_argument("--refresh", action="store_true",
                    help="rewrite the cache from Crossref (the only network mode)")
    ap.add_argument("--registry", default=None,
                    help="path to the checked-in DOI cache "
                         "(default: dois_registry.json next to this script)")
    args = ap.parse_args(argv)

    registry_path = Path(args.registry) if args.registry else default_registry_path()

    if args.refresh:
        return refresh(args.dir, registry_path)

    result = run_check(args.dir, registry_path)
    findings = result["findings"]
    matched = result["matched_by"]

    matched_str = " ".join(f"{field}={matched.get(field, 0)}"
                           for field in YEAR_FIELDS)
    print(
        f"pages={result['pages']} occurrences={len(result['occurrences'])} "
        f"distinct_dois={result['distinct']} "
        f"verified_occurrences={result['verified']} "
        f"unverified_occurrences={len(result['occurrences']) - result['verified']} "
        f"year_candidates_matched=({matched_str})"
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
