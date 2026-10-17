#!/usr/bin/env python3
"""Self-test for check_dois.py -- the coverage blind spots it fixes.

Runs the checker against throwaway fixture directories and a fixture cache, with
NO NETWORK AT ALL, and requires ALL of the following to hold:

  (i)   a DOI whose registry title belongs to a different paper is flagged
        TITLE MISMATCH (the closed-world checkers cannot see this, because the
        page is internally consistent);
  (ii)  a DOI that appears on a page but is absent from the cache is flagged
        DOI NOT IN CACHE -- a coverage gap, never a silent pass;
  (iii) a volume/issue disagreement between the page and the registry is flagged
        LOCATOR MISMATCH;
  (iv)  a correct pairing stays GREEN, INCLUDING the online-first-year case: the
        page cites (2024), ``issued``/``published-online`` are 2022, and only
        ``published-print`` is 2024, so no year finding is raised;
  (v)   a page title that is cut short (a prefix of the registry title) still
        matches: the comparison is a tolerant prefix/containment test, not
        string equality.

The cache itself ages, so its own stamp is checked too -- a check that can never
notice its own staleness is the failure these four cases exist to close:

  (vi)  a cache stamped 2025-01-01, read at --now 2026-10-17, is flagged
        STALE CACHE (with the age in days, the stamp, and the --refresh command),
        AND the per-DOI resolution still runs: a stale answer is still evidence;
  (vii) a cache with no ``fetched_at`` is flagged UNDATED CACHE -- an absent
        stamp must never read as fresh;
  (viii)a cache stamped 2027-01-01, read at --now 2026-10-17, is flagged
        FUTURE CACHE -- a future stamp is a broken clock, not freshness;
  (ix)  a cache inside the limit stays green.

Every case passes the clock with ``--now`` and the cache with ``--registry``, so
this test is hermetic: no network at all, and no dependence on the wall clock.
Stdlib only.  Exits 0 iff every case behaves; prints which case failed.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_dois.py"


def run_checker(files, registry, now="2026-01-02T00:00:00Z"):
    """Materialise *files* and a fixture *registry* and run the checker.

    Returns ``(returncode, stdout)``.  The registry is passed with ``--registry``
    so the checked-in cache is never consulted and no network call is possible;
    the clock is pinned with ``--now`` so no case depends on the wall clock.
    """
    tmp = Path(tempfile.mkdtemp(prefix="dois-selftest-"))
    try:
        for name, body in files.items():
            (tmp / name).write_text(body)
        reg = tmp / "fixture_registry.json"
        reg.write_text(json.dumps(registry, indent=2))
        proc = subprocess.run(
            [sys.executable, str(CHECKER), str(tmp),
             "--registry", str(reg), "--now", now],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


DOI = "10.1007/s11097-022-09811-z"
CORRECT_TITLE = ("Evidence synthesis indicates contentless experiences in "
                 "meditation are neither truly contentless nor identical")

# The real record shape, including the online-first trap: issued/online are
# 2022, the printed issue is 2024, and the page correctly cites (2024).
REAL_RECORD = {
    "title": CORRECT_TITLE,
    "container": "Phenomenology and the Cognitive Sciences",
    "volume": "23",
    "issue": "2",
    "page": "253-304",
    "years": {"published-print": "2024", "issued": "2022",
              "published-online": "2022"},
}


def registry_with(record, doi=DOI):
    return {"fetched_at": "2026-01-01T00:00:00Z", doi: record}


# --- fixtures -------------------------------------------------------------

CORRECT_PAIRING = f"""<!doctype html><html><body>
<p class="ref">Woods, T. J., Windt, J. M., &amp; Carter, O. (2024). Evidence synthesis indicates contentless experiences in meditation are neither truly contentless nor identical. <em>Phenomenology and the Cognitive Sciences</em>, 23(2), 253&ndash;304. DOI {DOI}</p>
</body></html>
"""

WRONG_TITLE = f"""<!doctype html><html><body>
<p class="ref">Woods, T. J., Windt, J. M., &amp; Carter, O. (2024). The path to contentless experience in meditation: an evidence synthesis based on expert texts. <em>Phenomenology and the Cognitive Sciences</em>, 23(2), 253&ndash;304. DOI {DOI}</p>
</body></html>
"""

MISSING_DOI = """<!doctype html><html><body>
<p class="ref">Someone (2024). A paper that was never cached at all. <em>Some Journal</em>, 1(1), 1-2. DOI 10.1234/not-in-registry</p>
</body></html>
"""

BAD_LOCATOR = f"""<!doctype html><html><body>
<p class="ref">Woods, T. J., Windt, J. M., &amp; Carter, O. (2024). Evidence synthesis indicates contentless experiences in meditation are neither truly contentless nor identical. <em>Phenomenology and the Cognitive Sciences</em>, 99(1), 253&ndash;304. DOI {DOI}</p>
</body></html>
"""

NEURO_DOI = "10.1016/j.neuroimage.2026.121906"

# The page cuts the title short with a trailing ellipsis, exactly as markup can;
# the registry carries the full title, so only a tolerant prefix test matches.
TRUNCATED_TITLE = f"""<!doctype html><html><body>
<p class="ref">Tan, S. H., Leuk, J. S. P. &amp; Teo, W.-P. (2026). Inter-brain synchrony during collaborative gaming: an investigation using theta-burst stimulation at the right temporal-parietal ... <em>NeuroImage</em>, 332, 121906. DOI {NEURO_DOI}</p>
</body></html>
"""

TRUNCATED_RECORD = {
    "title": ("Inter-brain synchrony during collaborative gaming: an "
              "investigation using theta-burst stimulation at the right "
              "temporal-parietal junction"),
    "container": "NeuroImage",
    "volume": "332",
    "issue": None,
    "page": "121906",
    "years": {"published-print": "2026", "issued": "2026",
              "published-online": None},
}


# --- cases ----------------------------------------------------------------

def case_wrong_registry_title():
    rc, out = run_checker({"wrong.html": WRONG_TITLE},
                          registry_with(REAL_RECORD))
    if "TITLE MISMATCH" not in out:
        return f"a registry title belonging to another paper was not flagged:\n{out}"
    if rc == 0:
        return f"a title mismatch exited 0:\n{out}"
    return None


def case_missing_from_cache():
    rc, out = run_checker({"missing.html": MISSING_DOI},
                          {"fetched_at": "2026-01-01T00:00:00Z"})
    if "DOI NOT IN CACHE" not in out:
        return f"a DOI absent from the cache was not reported as a gap:\n{out}"
    if "unverified_occurrences=1" not in out:
        return f"the coverage line did not name the unverified occurrence:\n{out}"
    if rc == 0:
        return f"an uncached DOI exited 0:\n{out}"
    return None


def case_bad_locator():
    rc, out = run_checker({"locator.html": BAD_LOCATOR},
                          registry_with(REAL_RECORD))
    if "LOCATOR MISMATCH" not in out:
        return f"a volume/issue disagreement was not flagged:\n{out}"
    if rc == 0:
        return f"a locator mismatch exited 0:\n{out}"
    return None


def case_correct_pairing_online_first_year():
    rc, out = run_checker({"correct.html": CORRECT_PAIRING},
                          registry_with(REAL_RECORD))
    if "FINDINGS: none" not in out:
        return f"a correct pairing with an online-first issued year was flagged:\n{out}"
    if "occurrences=1" not in out or "verified_occurrences=1" not in out:
        return f"the correct pairing was not counted as verified:\n{out}"
    if "published-print=1" not in out:
        return f"the matching year candidate was not recorded:\n{out}"
    if rc != 0:
        return f"a correct pairing exited {rc}:\n{out}"
    return None


def case_truncated_title_matches():
    rc, out = run_checker({"truncated.html": TRUNCATED_TITLE},
                          registry_with(TRUNCATED_RECORD, doi=NEURO_DOI))
    if "FINDINGS: none" not in out:
        return f"a page title that is a prefix of the registry title was flagged:\n{out}"
    if rc != 0:
        return f"a truncated-but-correct title exited {rc}:\n{out}"
    return None


def case_stale_cache_goes_red():
    """(vi) a 2025 stamp read in October 2026 is a finding, not a footnote."""
    rc, out = run_checker({"correct.html": CORRECT_PAIRING},
                          {"fetched_at": "2025-01-01T00:00:00Z",
                           DOI: REAL_RECORD},
                          now="2026-10-17T00:00:00Z")
    if "STALE CACHE" not in out:
        return f"a cache over 180 days old was not flagged STALE CACHE:\n{out}"
    if "654 days" not in out:
        return f"the stale-cache message did not state the age in days:\n{out}"
    if "2025-01-01T00:00:00Z" not in out:
        return f"the stale-cache message did not state the stamp:\n{out}"
    if "--refresh" not in out or "commit" not in out:
        return f"the stale-cache message did not name the fix to run:\n{out}"
    # A stale answer is still evidence: the per-DOI checks must NOT be skipped.
    if "verified_occurrences=1" not in out or "FINDINGS: none" in out:
        return (f"staleness replaced instead of accompanied the per-DOI "
                f"resolution:\n{out}")
    if "cache_age_days=654" not in out:
        return f"the summary line did not carry the cache age:\n{out}"
    if rc == 0:
        return f"a stale cache exited 0, so CI would stay green:\n{out}"
    return None


def case_undated_cache_goes_red():
    """(vii) no stamp at all must never read as fresh."""
    rc, out = run_checker({"correct.html": CORRECT_PAIRING}, {DOI: REAL_RECORD},
                          now="2026-10-17T00:00:00Z")
    if "UNDATED CACHE" not in out:
        return f"a cache with no fetched_at was not flagged:\n{out}"
    if "cache_age_days=undated" not in out:
        return f"an undated cache did not print cache_age_days=undated:\n{out}"
    if rc == 0:
        return f"an undated cache exited 0, so CI would stay green:\n{out}"
    return None


def case_future_cache_goes_red():
    """(viii) a stamp in the future is a broken clock, not freshness."""
    rc, out = run_checker({"correct.html": CORRECT_PAIRING},
                          {"fetched_at": "2027-01-01T00:00:00Z",
                           DOI: REAL_RECORD},
                          now="2026-10-17T00:00:00Z")
    if "FUTURE CACHE" not in out:
        return f"a cache stamped in the future was not flagged:\n{out}"
    if "2027-01-01T00:00:00Z" not in out:
        return f"the future-cache message did not state the stamp:\n{out}"
    if rc == 0:
        return f"a future-dated cache exited 0, so CI would stay green:\n{out}"
    return None


def case_fresh_cache_stays_green():
    """(ix) a cache inside the limit is not a finding."""
    rc, out = run_checker({"correct.html": CORRECT_PAIRING},
                          registry_with(REAL_RECORD),
                          now="2026-01-05T00:00:00Z")
    if "FINDINGS: none" not in out:
        return f"a fresh cache was flagged:\n{out}"
    if "UNDATED CACHE" in out or "STALE CACHE" in out or "FUTURE CACHE" in out:
        return f"a fresh cache produced a stamp finding:\n{out}"
    if "cache_age_days=4 " not in out:
        return f"the summary line did not carry the fresh cache age:\n{out}"
    if rc != 0:
        return f"a fresh cache exited {rc}:\n{out}"
    return None


CASES = [
    ("(i) registry title of another paper -> TITLE MISMATCH",
     case_wrong_registry_title),
    ("(ii) DOI absent from cache -> DOI NOT IN CACHE",
     case_missing_from_cache),
    ("(iii) volume/issue disagreement -> LOCATOR MISMATCH",
     case_bad_locator),
    ("(iv) correct pairing incl. online-first year stays green",
     case_correct_pairing_online_first_year),
    ("(v) truncated page title still matches (tolerant)",
     case_truncated_title_matches),
    ("(vi) cache dated 2025-01-01 read at --now 2026-10-17 -> STALE CACHE",
     case_stale_cache_goes_red),
    ("(vii) cache with no fetched_at -> UNDATED CACHE",
     case_undated_cache_goes_red),
    ("(viii) cache dated 2027-01-01 read at --now 2026-10-17 -> FUTURE CACHE",
     case_future_cache_goes_red),
    ("(ix) fresh cache stays green",
     case_fresh_cache_stays_green),
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
    print("\nall DOI-checker coverage cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
