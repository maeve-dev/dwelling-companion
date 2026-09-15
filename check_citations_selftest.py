#!/usr/bin/env python3
"""Self-test for check_citations.py -- the reference coverage it must have.

Every fixture is materialised in a fresh temp directory and the checker is run
as a subprocess.  The checker and this file are resolved relative to this
file's own ``__file__``, so the test works from any working directory.

Asserts:
  1. a well-formed reference (author, year, title, <em> venue, volume, pages)
     produces NO finding;
  2. the SAME reference with the venue NOT in <em> still has its title
     extracted and produces no title-related finding;
  3. a <div class="ref"> with two <div class="ref-item"> children counts as
     TWO references, and a bare <strong>References</strong> child counts as
     ZERO;
  4. "Frontiers in Human Neuroscience (2022)." is flagged NO AUTHOR;
  5. a title-before-year reference is flagged;
  6. --strict over a directory containing defect (4) exits 1, and over a
     defect-free directory exits 0;
  7. the COVERAGE: line is printed in both of those cases.

Stdlib only.  Exits 0 iff every assertion holds; on failure it prints which
assertion failed and exits non-zero.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_citations.py"


def run_checker(files, extra_args=()):
    """Materialise *files* in a temp dir and run the checker over it.

    Returns ``(returncode, stdout)``.
    """
    tmp = Path(tempfile.mkdtemp(prefix="citations-selftest-"))
    try:
        for name, body in files.items():
            (tmp / name).write_text(body)
        proc = subprocess.run(
            [sys.executable, str(CHECKER), str(tmp), *extra_args],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- fixtures -------------------------------------------------------------

WELL_FORMED_REF = (
    "Author, A., &amp; Buthor, B. (2020). A well-formed title of the paper. "
    "<em>Journal of Testing</em>, 10(2), 100-110."
)

WELL_FORMED = f"""<!doctype html><html><body>
<p class="ref">{WELL_FORMED_REF}</p>
</body></html>
"""

# The same reference with the venue in plain prose instead of <em>.
PLAIN_VENUE = """<!doctype html><html><body>
<p class="ref">Author, A., &amp; Buthor, B. (2020). A well-formed title of the paper. Journal of Testing, 10(2), 100-110.</p>
</body></html>
"""

REF_ITEM_BLOCK = """<!doctype html><html><body>
<div class="ref">
  <div class="ref-item"><strong>References</strong></div>
  <div class="ref-item">Author, A. (2001). The first worked example. <em>Journal of Testing</em>, 1, 1-2.</div>
  <div class="ref-item">Buthor, B. (2002). The second worked example. <em>Journal of Testing</em>, 2, 3-4.</div>
</div>
</body></html>
"""

HEADING_ONLY = """<!doctype html><html><body>
<div class="ref">
  <div class="ref-item"><strong>References</strong></div>
</div>
</body></html>
"""

VENUE_AS_AUTHOR = """<!doctype html><html><body>
<p class="ref">Frontiers in Human Neuroscience (2022). Interbrain connectivity during shared breath focus.</p>
</body></html>
"""

TITLE_FIRST = """<!doctype html><html><body>
<p class="ref">Resonance frequency is not always stable over time and could be related to the inter-beat interval. (2021). <em>Scientific Reports</em>, 11, 11391.</p>
</body></html>
"""


# --- helpers --------------------------------------------------------------

def coverage_field(out, field):
    m = re.search(rf"COVERAGE:.*?\b{field}=(\d+)", out)
    return int(m.group(1)) if m else None


# --- assertions -----------------------------------------------------------

def case_well_formed_clean():
    rc, out = run_checker({"clean.html": WELL_FORMED}, extra_args=("--strict",))
    if rc != 0:
        return f"expected exit 0 for a well-formed reference, got {rc}:\n{out}"
    if "FINDINGS: none" not in out:
        return f"expected no findings for a well-formed reference:\n{out}"
    return None


def case_plain_venue_title_extracted():
    rc, out = run_checker({"plain.html": PLAIN_VENUE}, extra_args=("--strict",))
    if rc != 0:
        return f"expected exit 0 for a plain-prose venue, got {rc}:\n{out}"
    if "FINDINGS: none" not in out:
        return f"plain-prose venue produced a finding:\n{out}"
    if coverage_field(out, "refs_with_title") != 1:
        return (f"title was not extracted when the venue is not <em> "
                f"(refs_with_title != 1):\n{out}")
    return None


def case_ref_item_counting():
    rc, out = run_checker({"items.html": REF_ITEM_BLOCK})
    total = coverage_field(out, "refs_total")
    if total != 2:
        return (f"<div class=\"ref\"> with two ref-item children must count "
                f"as TWO references, got refs_total={total}:\n{out}")
    rc2, out2 = run_checker({"heading.html": HEADING_ONLY})
    total2 = coverage_field(out2, "refs_total")
    if total2 != 0:
        return (f"a bare <strong>References</strong> heading must count as "
                f"ZERO, got refs_total={total2}:\n{out2}")
    return None


def case_venue_as_author():
    rc, out = run_checker({"venue.html": VENUE_AS_AUTHOR}, extra_args=("--strict",))
    if "NO AUTHOR" not in out:
        return f"venue-as-author reference was not flagged NO AUTHOR:\n{out}"
    if rc != 1:
        return f"expected exit 1 under --strict, got {rc}:\n{out}"
    return None


def case_title_first():
    rc, out = run_checker({"title.html": TITLE_FIRST}, extra_args=("--strict",))
    if "NO AUTHOR" not in out:
        return f"title-before-year reference was not flagged:\n{out}"
    if rc != 1:
        return f"expected exit 1 under --strict, got {rc}:\n{out}"
    return None


def case_strict_exit_codes_and_coverage():
    rc, out = run_checker({"defect.html": VENUE_AS_AUTHOR}, extra_args=("--strict",))
    if rc != 1:
        return f"--strict over a defect directory must exit 1, got {rc}:\n{out}"
    if "COVERAGE:" not in out:
        return f"--strict over a defect directory printed no COVERAGE: line:\n{out}"
    rc2, out2 = run_checker({"clean.html": WELL_FORMED}, extra_args=("--strict",))
    if rc2 != 0:
        return f"--strict over a clean directory must exit 0, got {rc2}:\n{out2}"
    if "COVERAGE:" not in out2:
        return f"--strict over a clean directory printed no COVERAGE: line:\n{out2}"
    return None


CASES = [
    ("(1) well-formed reference produces no finding", case_well_formed_clean),
    ("(2) plain-prose venue still yields a title", case_plain_venue_title_extracted),
    ("(3) ref-item children counted, heading not", case_ref_item_counting),
    ("(4) venue-as-author flagged NO AUTHOR", case_venue_as_author),
    ("(5) title-before-year reference flagged", case_title_first),
    ("(6/7) --strict exit codes and COVERAGE line",
     case_strict_exit_codes_and_coverage),
]


def main():
    if not CHECKER.exists():
        print(f"FAIL: checker not found at {CHECKER}")
        return 1
    failed = []
    for name, fn in CASES:
        problem = fn()
        if problem:
            failed.append(name)
            print(f"FAIL {name}\n     {problem}")
        else:
            print(f"ok   {name}")
    if failed:
        print(f"\n{len(failed)} assertion(s) failed: {', '.join(failed)}")
        return 1
    print("\nall citation-checker coverage assertions pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
