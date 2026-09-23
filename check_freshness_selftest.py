#!/usr/bin/env python3
"""Self-test for check_freshness.py -- it must go red, and it must not over-flag.

A checker that cannot go red is not a checker, and a checker that flags honest
wording is worse than none. This runs check_freshness.py against throwaway
fixture pages in a temp directory and requires BOTH directions to hold:

  (i)   EVERY seeded freshness/liveness construction, placed in a fixture page,
        makes the checker exit 1 and print a ``file:line: pattern`` hit for
        that construction -- one fixture per pattern, each fixture carrying its
        phrase exactly once on each of two known lines, so a fixture that
        accidentally satisfies two patterns fails the case instead of passing
        silently;
  (ii)  honest phrasings stay GREEN. The word "live" on this site also names a
        client-side interactive feature, not a freshness claim: the fixture
        modelled on breathing-circle-live.html carries "live calibration",
        "live circle", "breathing circle — live", "live — seed data" and "the
        radar chart updates live", and must produce no hits at all. This is the
        over-flagging negative control the brief calls out;
  (iii) the CORRECTED dashboard.html wording stays green -- checked twice: as a
        fixture page modelled on it, and by running the checker over the real
        dashboard.html and index.html copied out of the repo;
  (iv)  the PATTERNS list still contains every construction the class was
        seeded with, so a pattern cannot be silently dropped from the checker.

Stdlib only.  Exits 0 iff every case behaves; prints which case failed.
"""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_freshness.py"


def run_checker(files, extra_from_repo=()):
    """Materialise *files* (and repo copies) in a temp dir and run the checker.

    Returns ``(returncode, stdout)``.
    """
    tmp = Path(tempfile.mkdtemp(prefix="freshness-selftest-"))
    try:
        for name, body in files.items():
            (tmp / name).write_text(body)
        for name in extra_from_repo:
            shutil.copy(HERE / name, tmp / name)
        proc = subprocess.run(
            [sys.executable, str(CHECKER), str(tmp)],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_patterns():
    """Import the checker and return its PATTERNS list."""
    spec = importlib.util.spec_from_file_location("check_freshness", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PATTERNS


# --- fixtures -------------------------------------------------------------

# Two lines carry the phrase (2 and 5), so the expected hits are known exactly.
PAGE = """<!doctype html><html><head>
<meta name="description" content="{phrase}">
<title>fixture</title>
</head><body>
<p>{phrase}</p>
</body></html>
"""

# One fixture per seeded construction. Each phrase is written the way the site
# phrased it (or would phrase it) and satisfies exactly ONE pattern.
SEED_PHRASES = {
    "live state": "Dashboard — Live state, open PRs, dream fragments",
    "live dashboard": "A live dashboard of the system",
    "live data": "Showing live data from the system",
    "real-time": "A real-time view of the system",
    "real time": "System stats in real time",
    "updated automatically": "This page is updated automatically",
    "automatically updated": "Automatically updated on every push",
    "updated when the": "Updated when the dwelling companion is rebuilt",
    "always current": "The page is always current",
    "always up to date": "Always up to date",
    "up to the minute": "Up to the minute system stats",
    "up-to-the-minute": "An up-to-the-minute view",
}

# Required seeds named in the brief: dropping one from the checker must fail.
REQUIRED_SEEDS = [
    "live state",
    "live dashboard",
    "live data",
    "real-time",
    "updated automatically",
    "updated when the",
    "always current",
    "up to the minute",
]

# Modelled on breathing-circle-live.html: an interactive, client-side page whose
# "live" is a feature, not a claim to be current. Must produce zero hits.
HONEST_LIVE_FEATURE = """<!doctype html><html><head>
<meta name="description" content="A live breathing circle that adapts as you breathe, for settling into a steady, unhurried rhythm.">
<title>breathing circle — live</title>
</head><body>
<h1>breathing circle — live</h1>
<a class="piece-link" href="breathing-circle-live.html">Breathing circle — live calibration</a>
<p>Start the live circle and follow it in.</p>
<p>Move each slider to reflect your current experience. The radar chart updates live.</p>
<script>
  statusText.textContent = 'live — seed data';
</script>
</body></html>
"""

# Modelled on the corrected dashboard.html: a dated, hand-typed snapshot.
HONEST_DASHBOARD = """<!doctype html><html><head>
<meta name="description" content="A dated snapshot of the system behind this quiet — system info, open PRs, dream fragments, as of 2026-06-24.">
<title>see — dwelling companion</title>
</head><body>
<p class="snapshot-note">This page is a dated snapshot, typed by hand on <time datetime="2026-06-24">24 June 2026</time>. Nothing regenerates it. Read every number below as of that date, not as of the day you are reading this.</p>
<div class="card">open PRs — #439, #438, #437, as of 2026-06-24</div>
<p class="refresh-note">These figures are typed by hand, not generated: no build regenerates them. The site is redeployed whenever master moves, but the redeploy leaves this snapshot untouched, so every number above is still the one entered on 24 June 2026.</p>
<a class="piece-link" href="dashboard.html">Dashboard — a dated snapshot (24 June 2026): system, open PRs, dream fragments</a>
</body></html>
"""


# --- cases ----------------------------------------------------------------

def case_pattern(phrase, pattern):
    """The checker must go red for *phrase*, naming file, line and pattern."""
    rc, out = run_checker({"page.html": PAGE.format(phrase=phrase)})
    if rc != 1:
        return (f"expected exit 1 for {pattern!r} (fixture said {phrase!r}), "
                f"got {rc}:\n{out}")
    expected = [f"page.html:2: {pattern}", f"page.html:5: {pattern}"]
    missing = [line for line in expected if line not in out]
    if missing:
        return (f"expected the hit line(s) {missing} for {pattern!r}, got:\n{out}")
    if "files scanned: 1  hits found: 2" not in out:
        return (f"expected exactly 2 hits (the phrase appears twice in the "
                f"fixture), got:\n{out}")
    if "hits found:" not in out:
        return f"checker printed no summary line:\n{out}"
    return None


def case_honest_live_feature():
    rc, out = run_checker({"breathing-circle-live.html": HONEST_LIVE_FEATURE})
    if rc != 0 or "hits found: 0" not in out:
        return (f"honest interactive 'live calibration'/'live circle' wording "
                f"was flagged (rc={rc}):\n{out}")
    return None


def case_honest_dashboard_fixture():
    rc, out = run_checker({"dashboard.html": HONEST_DASHBOARD})
    if rc != 0 or "hits found: 0" not in out:
        return f"corrected dashboard wording was flagged (rc={rc}):\n{out}"
    return None


def case_real_pages_green():
    rc, out = run_checker({}, extra_from_repo=("dashboard.html", "index.html"))
    if rc != 0 or "hits found: 0" not in out:
        return (f"the real corrected dashboard.html/index.html are not green "
                f"(rc={rc}):\n{out}")
    if "files scanned: 2" not in out:
        return f"expected both real pages to be scanned, got:\n{out}"
    return None


def case_patterns_cover_seeds():
    patterns = load_patterns()
    missing = [p for p in REQUIRED_SEEDS if p not in patterns]
    if missing:
        return f"seeded constructions missing from PATTERNS: {missing}"
    return None


CASES = [(f"(i) {pattern!r} is flagged", case_pattern, (phrase, pattern))
         for pattern, phrase in SEED_PHRASES.items()]
CASES += [
    ("(ii) honest live-feature wording stays green", case_honest_live_feature, ()),
    ("(iii) corrected dashboard fixture stays green", case_honest_dashboard_fixture, ()),
    ("(iii) real dashboard.html/index.html stay green", case_real_pages_green, ()),
    ("(iv) PATTERNS still covers every seeded construction", case_patterns_cover_seeds, ()),
]


def main():
    if not CHECKER.exists():
        print(f"FAIL: checker not found at {CHECKER}")
        return 1
    failed = []
    for name, fn, args in CASES:
        problem = fn(*args)
        if problem:
            failed.append(name)
            print(f"FAIL {name}\n     {problem}")
        else:
            print(f"ok   {name}")
    if failed:
        print(f"\n{len(failed)} case(s) failed: {', '.join(failed)}")
        return 1
    print(f"\nall freshness-checker cases pass ({len(CASES)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
