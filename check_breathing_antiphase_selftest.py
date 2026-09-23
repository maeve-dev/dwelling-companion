#!/usr/bin/env python3
"""Self-test for check_breathing_antiphase.py.

A checker is only worth its green tick if it is known to go red. This runs the
checker against mutated copies of the real page and requires each mutation to
be caught -- and requires the pristine page, and a change that is NOT a
violation, to stay green.

Cases:

  (i)   the unmodified page passes (the baseline is genuinely clean);
  (ii)  the two circles made IN PHASE are flagged (the real break mode);
  (iii) a stop whose opacity is not the complement is flagged -- anti-phase is
        checked on every animated channel, not just transform;
  (iv)  an animation-delay is flagged;
  (v)   the JS speed control giving the circles different durations is flagged;
  (vi)  a 100% stop that disagrees with 0% is flagged (the loop does not close);
  (vii) swapping the two keyframe blocks is NOT flagged -- anti-phase is a
        symmetric relation, so relabelling the circles cannot break it. This is
        a negative control against overflagging;
  (viii) a missing target exits non-zero rather than passing vacuously.

Stdlib only.  Exits 0 iff every case behaves; prints which case failed.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "shared-breathing-circle.html"
CHECKER = ROOT / "check_breathing_antiphase.py"

# The exact text of the two keyframe bodies in the shipped page.
A_BODY = (
    "@keyframes breathe-a {\n"
    "    0%, 100% { transform: scale(1); opacity: 0.6; }\n"
    "    50% { transform: scale(1.6); opacity: 1; }"
)
B_BODY = (
    "@keyframes breathe-b {\n"
    "    0%, 100% { transform: scale(1.6); opacity: 1; }\n"
    "    50% { transform: scale(1); opacity: 0.6; }"
)
B_HALF = "    0%, 100% { transform: scale(1.6); opacity: 1; }"
B_B_DECL = "    animation: breathe-b 8s ease-in-out infinite;"
JS_B_DUR = "circleB.style.animationDuration = duration + 's';"
A_STOP0 = "    0%, 100% { transform: scale(1); opacity: 0.6; }"


# breathe-b's header with breathe-a's stops: the circles breathe together.
B_BODY_IN_PHASE = B_BODY.split("\n")[0] + "\n" + "\n".join(A_BODY.split("\n")[1:])


def make_in_phase(text):
    """Give breathe-b the same body as breathe-a -- the circles breathe together.

    Only the BODY is swapped; the @keyframes name stays breathe-b. Replacing the
    whole block would delete breathe-b outright, which the checker would flag
    for an unrelated reason.
    """
    return text.replace(B_BODY, B_BODY_IN_PHASE)


def break_opacity(text):
    """Keep the scales complementary but break the opacity channel."""
    return text.replace(B_HALF, "    0%, 100% { transform: scale(1.6); opacity: 0.9; }")


def add_delay(text):
    return text.replace(B_B_DECL, B_B_DECL + "\n    animation-delay: 1s;")


def diverge_js_duration(text):
    return text.replace(
        JS_B_DUR, "circleB.style.animationDuration = (duration + 1) + 's';"
    )


def break_loop(text):
    """A 100% stop that disagrees with 0%: the loop no longer closes."""
    return text.replace(
        A_STOP0,
        "    0% { transform: scale(1); opacity: 0.6; }\n"
        "    100% { transform: scale(1.2); opacity: 0.8; }",
    )


def swap_circles(text):
    """Relabel A and B. Symmetric: anti-phase survives, so this must NOT flag."""
    return text.replace(A_BODY, "@@A@@").replace(B_BODY, A_BODY).replace("@@A@@", B_BODY)


# (name, mutation, expect_failure, substring required in the output when failing)
CASES = [
    ("(i)   pristine page", lambda t: t, False, None),
    ("(ii)  circles made in phase", make_in_phase, True, "NOT anti-phase"),
    ("(iii) opacity not complementary", break_opacity, True, "NOT anti-phase"),
    ("(iv)  animation-delay added", add_delay, True, "animation-delay"),
    ("(v)   JS duration divergence", diverge_js_duration, True, "different durations"),
    ("(vi)  loop does not close", break_loop, True, "does not close"),
    ("(vii) circles relabelled (symmetric)", swap_circles, False, None),
]


def run_checker(path):
    proc = subprocess.run(
        [sys.executable, str(CHECKER), str(path)],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main():
    if not PAGE.is_file():
        print(f"selftest: cannot find {PAGE}")
        return 1

    base = PAGE.read_text(errors="replace")
    failures = []
    tmp = tempfile.mkdtemp(prefix="breathing-antiphase-selftest-")
    try:
        for name, mutate, expect_failure, needle in CASES:
            mutated = mutate(base)
            if mutated == base and mutate is not CASES[0][1]:
                # Guard: a mutation whose anchor no longer matches would pass
                # vacuously, which is the failure this selftest exists to catch.
                failures.append(f"{name}: mutation did not change the text (stale anchor)")
                continue
            case_dir = Path(tmp) / name.split()[0].strip("()")
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / PAGE.name).write_text(mutated)
            code, output = run_checker(case_dir)
            if expect_failure:
                if code == 0:
                    failures.append(f"{name}: expected failure, got exit 0")
                elif needle not in output:
                    failures.append(f"{name}: failed but not with {needle!r}: {output.strip()}")
                else:
                    print(f"ok   {name} -> caught: {needle}")
            else:
                if code != 0:
                    failures.append(f"{name}: expected pass, got exit {code}: {output.strip()}")
                else:
                    print(f"ok   {name} -> not flagged (correct)")

        # (viii) a missing file must exit non-zero, never pass vacuously.
        empty = Path(tmp) / "empty"
        empty.mkdir(exist_ok=True)
        code, _ = run_checker(empty)
        if code == 0:
            failures.append("(viii) missing file: expected non-zero exit, got 0")
        else:
            print("ok   (viii) missing file -> non-zero exit")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print()
        for f in failures:
            print(f"FAIL {f}")
        return 1
    print("\nall anti-phase checker cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
