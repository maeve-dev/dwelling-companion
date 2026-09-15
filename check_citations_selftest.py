#!/usr/bin/env python3
"""Self-test for check_citations.py -- the coverage blind spots it fixes.

Runs the checker against a set of throwaway fixture directories and requires
ALL of the following to hold:

  (i)   a ``<div class="ref">`` block whose ``class="ref-item"`` children are
        the real references is counted (the old checker saw none of them);
  (ii)  a reference whose author position is a journal/preprint name is
        flagged NO AUTHOR;
  (iii) a title-first reference (year after the title, no author) is flagged
        NO AUTHOR;
  (iv)  a clean reference whose venue is plain prose (no ``<em>``) is still
        entered into the key-consistency comparison;
  (v)   two genuinely different works by the same first author and year, with
        different titles, do NOT produce a venue/locator disagreement;
  (vi)  a footnote container (``<p id="fnN">``) is both COUNTED and
        ANALYSED: the leading footnote number is stripped, and a journal
        sitting in its author position is flagged NO AUTHOR.

Stdlib only.  Exits 0 iff every case behaves; prints which case failed.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_citations.py"


def run_checker(files):
    """Materialise *files* in a temp dir and run the checker over it.

    Returns ``(returncode, stdout)``.
    """
    tmp = Path(tempfile.mkdtemp(prefix="citations-selftest-"))
    try:
        for name, body in files.items():
            (tmp / name).write_text(body)
        proc = subprocess.run(
            [sys.executable, str(CHECKER), str(tmp)],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- fixtures -------------------------------------------------------------

DIV_BLOCK = """<!doctype html><html><body>
<div class="ref">
  <div class="ref-item"><strong>References</strong></div>
  <div class="ref-item">Gamma, A., &amp; Metzinger, T. (2021). The Minimal Phenomenal Experience questionnaire. <em>PLOS One</em>, 16(7), e0253694.</div>
  <div class="ref-item">Friston, K. (2010). The free-energy principle: a unified brain theory? <em>Nature Reviews Neuroscience</em>, 11(2), 127-138.</div>
</div>
</body></html>
"""

VENUE_AS_AUTHOR = """<!doctype html><html><body>
<p class="ref">Nature Scientific Reports (2025). Heart rate variability biofeedback in a global study of the most common coherence frequencies.</p>
</body></html>
"""

TITLE_FIRST = """<!doctype html><html><body>
<p class="ref">Resonance frequency is not always stable over time and could be related to the inter-beat interval. (2021). <em>Scientific Reports</em>, 11, 87867.</p>
</body></html>
"""

PLAIN_VENUE = """<!doctype html><html><body>
<p class="ref">Lehrer, P. M., &amp; Gevirtz, R. (2014). Heart rate variability biofeedback: how and why does it work? Frontiers in Psychology, 5, 756.</p>
</body></html>
"""

TWO_DIFFERENT_WORKS = """<!doctype html><html><body>
<p class="ref">Balconi, M., &amp; Angioletti, L. (2023). Dyadic inter-brain EEG coherence induced by interoceptive hyperscanning. <em>Scientific Reports</em>, 13, 31494.</p>
<p class="ref">Balconi, M., &amp; Angioletti, L. (2023). Autonomic synchrony induced by hyperscanning interoception during interpersonal synchronization tasks. <em>Frontiers in Human Neuroscience</em>, 17, 1200750.</p>
</body></html>
"""

FOOTNOTE_BLOCK = """<!doctype html><html><body>
<p id="fn1"><sup>1</sup> Gamma, A., &amp; Metzinger, T. (2021). The Minimal Phenomenal Experience questionnaire. <em>PLOS One</em>, 16(7), e0253694.</p>
<p id="fn2"><sup>2</sup> Frontiers in Human Neuroscience (2022). Inter-brain EEG during shared attention.</p>
</body></html>
"""


# --- cases ----------------------------------------------------------------

def case_div_block():
    rc, out = run_checker({"div.html": DIV_BLOCK})
    if "refs=2" not in out:
        return (f"expected the <div class=ref> block to contribute 2 refs "
                f"(heading skipped), got:\n{out}")
    return None


def case_venue_as_author():
    rc, out = run_checker({"venue.html": VENUE_AS_AUTHOR})
    if "NO AUTHOR" not in out:
        return f"venue-as-author ref was not flagged NO AUTHOR:\n{out}"
    return None


def case_title_first():
    rc, out = run_checker({"title.html": TITLE_FIRST})
    if "NO AUTHOR" not in out:
        return f"title-first ref was not flagged NO AUTHOR:\n{out}"
    return None


def case_plain_venue_entered():
    rc, out = run_checker({"plain.html": PLAIN_VENUE})
    if "key_consistency_entered=1" not in out:
        return (f"plain-prose-venue ref was not entered into the "
                f"key-consistency comparison:\n{out}")
    return None


def case_different_works():
    rc, out = run_checker({"two.html": TWO_DIFFERENT_WORKS})
    if "DISAGREEMENT" in out:
        return (f"two different works by the same author/year produced a "
                f"venue/locator disagreement:\n{out}")
    if rc != 0:
        return f"expected exit 0 for two distinct clean works, got {rc}:\n{out}"
    return None



def case_footnote_container():
    rc, out = run_checker({"fn.html": FOOTNOTE_BLOCK})
    if "footnote=2" not in out:
        return (f"expected the two <p id=\"fnN\"> footnotes to be collected "
                f"as footnote refs, got:\n{out}")
    if "NO AUTHOR" not in out:
        return (f"a journal-in-author-position inside a footnote was not "
                f"flagged NO AUTHOR -- the container is counted but its "
                f"content is not analysed:\n{out}")
    return None


CASES = [
    ("(i) div.ref/ref-item block is counted", case_div_block),
    ("(ii) venue-as-author flagged NO AUTHOR", case_venue_as_author),
    ("(iii) title-first ref flagged NO AUTHOR", case_title_first),
    ("(iv) plain-prose venue still key-checked", case_plain_venue_entered),
    ("(v) distinct works do not disagree", case_different_works),
    ("(vi) footnote container counted and analysed", case_footnote_container),
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
        print(f"\n{len(failed)} case(s) failed: {', '.join(failed)}")
        return 1
    print("\nall citation-checker coverage cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
