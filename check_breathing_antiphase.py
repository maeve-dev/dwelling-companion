#!/usr/bin/env python3
"""Anti-phase invariant check for the shared breathing circle.

shared-breathing-circle.html draws two circles whose entire design rests on one
property: they are locked anti-phase, so one is smallest exactly when the other
is largest, for the whole run. That property has been re-verified by hand
several times, with the line numbers re-derived on each pass, because none of
the other checkers reads CSS keyframes. This one does.

It asserts four things about the file, and fails when any stops holding:

  1. @keyframes breathe-a and @keyframes breathe-b both exist.
  2. They declare the same set of stops, after folding 100% onto 0% -- an
     infinite animation's end is its start, so if the two disagree there the
     loop itself is broken.
  3. Each of A's stops is equal to B's values at the stop half a period away:
     A(0) == B(50) and A(50) == B(0). That is what "anti-phase" means here, and
     it is checked on EVERY animated channel (transform and opacity), not just
     transform.
  4. The two circles are driven with identical timing: the same duration and
     timing function in the CSS shorthand, no animation-delay on either, and
     the same duration expression everywhere the page rewrites a circle's
     animation in JavaScript.

Point 4 is the one that needs the JavaScript at all: the speed control
reassigns each circle's animation at runtime, so a pair given *different*
durations there would drift -- the exact failure the design is claimed to be
immune to.

Scope, stated plainly: this is a structural check, not a rendering test. It
cannot tell you the circles look right. It can tell you the invariant the
design rests on has not been broken -- which is the thing that was being
re-derived by hand.

Run from the repo root:  python3 check_breathing_antiphase.py [path]
    path may be the .html file or a directory containing it (default: ".").
Exit 0 if the invariant holds, 1 otherwise.
"""
import re
import sys
from pathlib import Path

TARGET = "shared-breathing-circle.html"

# A stop selector once, e.g. "0%, 100%"; and a CSS declaration block.
_STOP_RE = re.compile(r"([0-9]+%\s*(?:,\s*[0-9]+%\s*)*)\{([^}]*)\}")
_KF_RE = re.compile(r"@keyframes\s+([A-Za-z0-9_-]+)\s*\{(.*?)\n\s*\}", re.DOTALL)
_ANIM_SHORTHAND_RE = re.compile(r"animation:\s*([A-Za-z0-9_-]+)\s+([^;{}]+);")
_JS_DURATION_RE = re.compile(r"circle([AB])\.style\.animationDuration\s*=\s*([^;]+);")
_JS_ANIMATION_RE = re.compile(r"circle([AB])\.style\.animation\s*=\s*(`[^`]*`|'[^']*'|\"[^\"]*\")\s*;")


def parse_keyframes(text):
    """Return {name: {stop_int: frozenset(declarations)}} for every @keyframes."""
    out = {}
    for name, block in _KF_RE.findall(text):
        stops = {}
        for selector, decls in _STOP_RE.findall(block):
            decl_set = frozenset(
                d.strip() for d in decls.split(";") if d.strip()
            )
            for part in selector.split(","):
                pct = int(part.strip().rstrip("%"))
                stops.setdefault(pct, decl_set)
                if stops[pct] != decl_set:
                    # Same stop declared twice with different values.
                    stops[pct] = stops[pct] | decl_set
        out[name] = stops
    return out


def fold_loop(stops, problems, name):
    """Fold a 100% stop onto 0%. They must agree: an infinite loop closes."""
    if 100 in stops and 0 in stops:
        if stops[100] != stops[0]:
            problems.append(
                f"@{name}: 0% and 100% disagree, so the loop does not close -- "
                f"0%={sorted(stops[0])} 100%={sorted(stops[100])}"
            )
    if 100 in stops:
        del stops[100]
    return stops


def check_keyframes(kf, problems):
    for required in ("breathe-a", "breathe-b"):
        if required not in kf:
            problems.append(f"@keyframes {required} is missing")
    if problems:
        return
    a = fold_loop(dict(kf["breathe-a"]), problems, "breathe-a")
    b = fold_loop(dict(kf["breathe-b"]), problems, "breathe-b")

    if set(a) != set(b):
        problems.append(
            f"breathe-a and breathe-b declare different stops: "
            f"{sorted(a)} vs {sorted(b)}"
        )
        return

    for stop in sorted(a):
        shifted = (stop + 50) % 100
        if shifted not in b:
            problems.append(
                f"breathe-b has no stop at {shifted}%, which is the half-period "
                f"partner of breathe-a's {stop}% -- anti-phase is not expressible"
            )
            continue
        if a[stop] != b[shifted]:
            problems.append(
                f"NOT anti-phase at {stop}%: breathe-a {sorted(a[stop])} "
                f"should equal breathe-b at {shifted}% {sorted(b[shifted])}"
            )


def check_css_timing(text, problems):
    """Both circles must be driven by the same duration and timing function."""
    timing = {}
    for name, rest in _ANIM_SHORTHAND_RE.findall(text):
        timing.setdefault(name, []).append(" ".join(rest.split()))
    for name in ("breathe-a", "breathe-b"):
        entries = timing.get(name)
        if not entries:
            problems.append(f"no CSS `animation:` shorthand drives {name}")
        elif len(set(entries)) > 1:
            problems.append(
                f"{name} is driven with inconsistent timing: {sorted(set(entries))}"
            )
    if "breathe-a" in timing and "breathe-b" in timing:
        ta, tb = timing["breathe-a"][0], timing["breathe-b"][0]
        if ta != tb:
            problems.append(
                f"the two circles use different timing ({ta!r} vs {tb!r}) -- "
                f"equal duration and easing is what makes drift impossible"
            )
    if "animation-delay" in text:
        for lineno, line in enumerate(text.splitlines(), 1):
            if "animation-delay" in line:
                problems.append(
                    f"line {lineno}: animation-delay present -- a nonzero delay "
                    f"offsets the pair away from exact anti-phase"
                )


def check_js_timing(text, problems):
    """The speed control rewrites each circle's animation; keep them paired."""
    durations = {}
    for circle, expr in _JS_DURATION_RE.findall(text):
        durations.setdefault(circle, []).append(" ".join(expr.split()))
    for circle in ("A", "B"):
        entries = durations.get(circle)
        if entries and len(set(entries)) > 1:
            problems.append(
                f"circle{circle}'s duration is assigned inconsistently in JS: "
                f"{sorted(set(entries))}"
            )
    if durations.get("A") and durations.get("B"):
        # Compare the last assignment of each -- that is the live one.
        da, db = durations["A"][-1], durations["B"][-1]
        if da != db:
            problems.append(
                f"JS gives the two circles different durations ({da!r} vs {db!r}) "
                f"-- a pair with unequal durations drifts"
            )

    paired = {}
    for circle, expr in _JS_ANIMATION_RE.findall(text):
        # Normalise the keyframe NAME away; the timing must still match.
        normalised = re.sub(r"breathe-[ab]", "breathe-X", " ".join(expr.split()))
        paired.setdefault(circle, []).append(normalised)
    if paired.get("A") and paired.get("B"):
        if paired["A"] != paired["B"]:
            problems.append(
                f"JS rewrites the two circles' animations differently: "
                f"A={paired['A']} B={paired['B']}"
            )


def main(argv):
    target = Path(argv[1]) if len(argv) > 1 else Path(".")
    path = target if target.is_file() else target / TARGET
    if not path.is_file():
        print(f"error: {TARGET} not found at {path}")
        return 1

    text = path.read_text(errors="replace")
    problems = []
    check_keyframes(parse_keyframes(text), problems)
    check_css_timing(text, problems)
    check_js_timing(text, problems)

    for p in problems:
        print(f"{path}: {p}")
    print(f"file: {path}  anti-phase violations: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
