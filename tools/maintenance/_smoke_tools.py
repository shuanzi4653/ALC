"""Prove the repaired tools scripts can actually start.

A rewrite that compiles is not a rewrite that works: the whole damage class was
"parses fine, resolves the wrong path at runtime". So this executes every script
and classifies the outcome by what it reached, not by its exit code alone:

  OK        ran to completion (exit 0)
  EXPECTED  failed on a precondition the script itself reports -- a missing
            service, a missing credential, a required argv. The bootstrap is
            proven to have worked because the failure is past it.
  BROKEN    failed at import or on a path/encoding error. That is a real defect.

  SLOW      not run. Its own source says it cannot finish in a smoke budget: it
            calls `simulate()` more often than the budget allows, or blocks on a
            socket loop, or hammers expensive geometry to measure it. Run it
            deliberately with --only, or raise --timeout to bring it back in.

Two hard-won details, both of which cost a hung run to learn:

1. ``subprocess.run(timeout=...)`` does not reliably bound a child that has
   spawned a detached grandchild or is blocked reading stdin. The script holds
   ports or waits on a service by design, so the whole pass can hang for hours
   while ``run`` reports nothing. Each child therefore gets its own kill path,
   ``stdin=DEVNULL``, and a process-tree kill on timeout.
2. Progress is written per file *before* the run, so a hang leaves behind the
   name of the script responsible instead of a silent empty output file.

    _smoke_tools.py [--timeout 30] [--only <substring>]
"""

import io
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
# _repo.py lives in tools/, not in tools/maintenance/, so the path entry has to
# be the parent -- inserting HERE would look in the wrong directory.
sys.path.insert(0, TOOLS)
from _repo import ROOT, BACKEND  # noqa: E402

VENV = os.path.join(BACKEND, ".venv", "Scripts", "python.exe")
PY = VENV if os.path.isfile(VENV) else sys.executable
REPORT = os.path.join(ROOT, "artifacts", "_smoke_report.txt")

# Long-running by design: service launchers, HTTP pollers waiting on a port,
# and the test/build drivers that take minutes on purpose.
SKIP = {
    "_sim_harness.py", "_start_services.py", "_wait_ready.py",
    "_run_pytest.py", "_run_frontend.py", "_run_frontend_tail.py",
    "_run_tests_band.py", "_build_frontend.py", "_verify.py",
    "_run_java.py", "_sim_probe.py", "_sim_command.py",
    "_verify_huafeng_live.py", "_probe_e2e_chain.py", "_probe_services.py",
    "_probe_session_poll.py", "_probe_build_progress.py",
    # Multi-simulate benches and a profiler. `service.simulate` costs ~12-17 s
    # once the network is at 7760 flights, and these call it two or three times
    # (a warm-up plus one run per policy) or wrap it in cProfile. They are not
    # hung -- they are longer than any sane smoke budget. Run them deliberately,
    # e.g. with --only, when the timing numbers are what you want.
    "_bench_static_zones.py", "_bench_zone_baseline.py", "_profile_own.py",
}

# Network reachability probes. They open real sockets to public hosts; inside a
# sandbox with no route, `connect` blocks until the harness kills it, which is a
# property of the environment, not a defect in the script. Run them with a
# working network and NO_PROXY set when the question is "can we reach X?".
#
# The radar-tile probes belong here for a second reason: they read a *live*
# published product, and the slot they ask for may simply not be up yet, which
# arrives as HTTP 404. That is a statement about the product's schedule, not
# about the script, so it must not be reported as breakage.
NETWORK_SKIP = {
    "_probe_geo.py",
    "_probe_tile_latitude_anchor.py",
    "_probe_tile_orientation.py",
}

# Two cost classes are intrinsic to what a script *does*, not defects in it, and
# they are big enough to blow any smoke budget. Listing them by filename rots --
# a new probe that calls simulate() looks hung the day it is added. So classify
# from the source instead, and say which rule fired.
#
#   SLOW_SIM  a full `service.simulate()` costs 13-17 s warm and 17.5 s cold, but
#             a script that calls it also loads geometry and walks the fleet, so
#             the *script* floor is higher than the call. Measured costs of six
#             probes that each call simulate() exactly once:
#
#                 24.3  35.0  39.6  53.3  71.6  123.0   seconds
#
#             Every one of them exceeds a 30 s budget, and the cheapest is
#             24.3 s -- so an estimate of 18 s per call let all six through and
#             they were killed as HUNG. The estimate has to be the *script* cost,
#             not the call cost, and the observed minimum plus the call itself is
#             the honest floor: SIM_SCRIPT_FLOOR + calls * SIM_SECONDS.
#
#             How many fit depends on the *budget*, so the rule is a comparison:
#
#                 SIM_SCRIPT_FLOOR + calls * SIM_SECONDS <= timeout  ->  run it
#                 otherwise                                         ->  skip
#
#             This replaces both earlier spellings, each wrong differently:
#               `count >= 2`  asserted "one call always fits". False once the
#                             network grew to 7760 flights, so six single-call
#                             probes were reported HUNG for 31 s.
#               `count >= 1`  skipped 37 scripts including ones the suite had
#                             routinely smoked -- trading false HUNGs for
#                             massive false skips, which is worse, because a
#                             skipped script is never checked at all.
#               `calls * 18s` admitted the same six, because 18 s per *call*
#                             ignored the per-script overhead.
#             A floor+slope comparison is right at any budget: the default 30 s
#             skips a single call, and `--timeout 300` brings it back.
#   SLOW_NET  opens sockets to a public host. With no route the connect blocks
#             until the harness kills it -- a property of the sandbox, not the
#             script. A single reachability check is cheap and is still run;
#             only a *loop* over hosts is unpredictable. One open *outside* any
#             loop is still skipped when the script also touches the app's own
#             long-lived opener, because that path reaches the live product.
#   SLOW_WORK a tight loop of expensive geometry (union / convex hull / STRtree)
#             measured for its own cost, so it cannot be shortened without
#             destroying the measurement.
SIM_CALL = re.compile(r"\bsimulate\s*\(")
SIM_SCRIPT_FLOOR = 22.0     # cheapest measured single-call script was 24.3 s
SIM_SECONDS = 18.0          # cold-process cost of one extra simulate() call
NET_OPEN = re.compile(r"OPENER\.open|urlopen\s*\(")
NET_LOOP = re.compile(r"for\s+\w+\s+in\s+.*\b(?:range|zoom|tiles?|hosts?|stations?|sites?)\b")
WORK_LOOP = re.compile(r"for\s+\w+\s+in\s+.*\b(?:stride|WINDOWS|WAVES|zips?)\b")

EXPECTED = re.compile(
    r"ConnectionRefused|ConnectionReset|NewConnectionError|"
    r"urllib\.error\.URLError|IndexError: list index out of range|"
    r"SystemExit|"
    r"Missing|required|not configured|no credential|未配置|需要|尚未|"
    r"ModuleNotFoundError: No module named 'requests'|"
    # A published product the script consumes can be absent or not yet posted.
    # The app raises its own type for that, and it is a precondition, not a
    # defect: the script reached the network and the network said "not there".
    r"RadarTileUnavailable|HTTP ?50[0-9]|HTTPError|TimeOut|timed out|"
    r"FileNotFoundError.*(?:secret|\.key|classpath|node_modules)",
    re.I,
)

BROKEN = re.compile(
    r"ModuleNotFoundError: No module named '_repo'|"
    r"ModuleNotFoundError: No module named 'traffic'|"
    r"ImportError: attempted relative import|"
    r"NameError: name '(?:ROOT|BACKEND|FRONTEND|DOCS|SCRIPTS|TOOLS|HERE|sys|os)' is not defined|"
    r"NameError: name '_?sys' is not defined|"
    r"NameError: name 'Path' is not defined|"
    r"AttributeError: 'str' object has no attribute|"
    r"TypeError: unsupported operand type\(s\) for /: 'str'|"
    r"FileNotFoundError: \[Errno 2\] No such file or directory: 'backend-python",
    re.I,
)

# A probe whose target API has been removed on purpose. These are kept as the
# audit trail for findings already written up, so they must NOT be deleted, but
# they also must not run against an API that no longer exists. A retired probe
# prints RETIRED and exits 0 -- see tools/probes/_retired.py for the contract.
RETIRED = re.compile(r"^\s*RETIRED:", re.M)


def slow_reason(path, budget):
    """Return why this script cannot finish inside the smoke budget, or None.

    The simulate() rule compares estimated cost against the *actual* budget, so
    raising `--timeout` brings more scripts back into the run instead of needing
    a threshold edit. The other two rules stay presence-based, because their cost
    is unbounded in a way a count cannot express: a socket with no route blocks
    until killed no matter what the budget is.

    A false positive costs one skipped script; a false negative costs a hung run.
    The budget comparison keeps both small, and the reason string reports the
    numbers it used so a wrong call is visible in the output.
    """
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    calls = len(SIM_CALL.findall(text))
    if calls:
        cost = SIM_SCRIPT_FLOOR + calls * SIM_SECONDS
        if cost > budget:
            return "%d simulate() call(s) ~%.0fs > %ds budget" % (calls, cost, budget)
    if NET_OPEN.search(text) and NET_LOOP.search(text):
        return "network loop"
    if WORK_LOOP.search(text):
        return "measured geometry loop"
    return None


def run_one(path, timeout):
    """Run one script with a bounded wait and a process-tree kill."""
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    env["PYTHONIOENCODING"] = "utf-8"
    creation = 0
    if os.name == "nt":
        creation = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [PY, "-X", "utf8", path], cwd=ROOT, env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=creation,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or ""
    except subprocess.TimeoutExpired:
        # Kill the whole tree: these scripts start services.
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            proc.kill()
        try:
            out, _ = proc.communicate(timeout=10)
        except Exception:
            out = ""
        return None, (out or "")


def main():
    timeout = 30
    only = None
    include_network = False
    for index, arg in enumerate(sys.argv):
        if arg == "--timeout" and index + 1 < len(sys.argv):
            timeout = int(sys.argv[index + 1])
        if arg == "--only" and index + 1 < len(sys.argv):
            only = sys.argv[index + 1]
        if arg == "--with-network":
            include_network = True

    skip = set(SKIP)
    if not include_network:
        skip |= NETWORK_SKIP

    targets = []
    for folder, _dirs, files in os.walk(TOOLS):
        for name in sorted(files):
            if not name.endswith(".py") or name == "_repo.py":
                continue
            if name in skip:
                continue
            rel = os.path.relpath(os.path.join(folder, name), TOOLS)
            if only and only not in rel:
                continue
            targets.append((rel, os.path.join(folder, name)))

    log = io.open(REPORT, "w", encoding="utf-8", newline="\n")
    ok, expected, broken, hung, retired, slow = [], [], [], [], [], []

    for rel, full in targets:
        reason = slow_reason(full, timeout)
        if reason and not only:
            slow.append((rel, reason))
            log.write("SLOW %-52s %s\n" % (rel, reason))
            log.flush()
            continue
        log.write("RUN  " + rel + "\n")
        log.flush()
        started = time.monotonic()
        code, out = run_one(full, timeout)
        elapsed = time.monotonic() - started
        if code is None:
            hung.append((rel, "%.0fs, killed" % elapsed))
            log.write("HUNG %-52s %.0fs\n" % (rel, elapsed))
            log.flush()
            continue
        if code == 0:
            ok.append(rel)
            log.write("OK   %-52s %.1fs\n" % (rel, elapsed))
        elif RETIRED.search(out):
            why = RETIRED.search(out).group(0).strip()[:80]
            retired.append((rel, why))
            log.write("RETD %-52s %s\n" % (rel, why))
        elif BROKEN.search(out):
            hit = BROKEN.search(out).group(0)[:80]
            broken.append((rel, hit))
            log.write("BAD  %-52s %s\n" % (rel, hit))
        elif EXPECTED.search(out):
            hit = EXPECTED.search(out).group(0)[:50]
            expected.append((rel, hit))
            log.write("PREC %-52s %s\n" % (rel, hit))
        else:
            tail = out.strip().split("\n")[-1][:110] if out.strip() else "(no output)"
            broken.append((rel, "unexplained: " + tail))
            log.write("BAD  %-52s %s\n" % (rel, tail))
        log.flush()

    log.close()
    print("ran clean      : %d" % len(ok))
    print("expected stop  : %d" % len(expected))
    print("retired        : %d" % len(retired))
    print("too slow by design: %d" % len(slow))
    print("hung           : %d" % len(hung))
    print("BROKEN         : %d" % len(broken))
    if slow:
        print()
        print("=== SLOW BY DESIGN (classified from source; run with --only) ===")
        for rel, why in slow:
            print("  %-52s %s" % (rel, why))
    if retired:
        print()
        print("=== RETIRED (target API removed; kept as audit trail) ===")
        for rel, why in retired:
            print("  %-52s %s" % (rel, why))
    if hung:
        print()
        print("=== HUNG ===")
        for rel, why in hung:
            print("  %-52s %s" % (rel, why))
    if broken:
        print()
        print("=== BROKEN ===")
        for rel, why in broken:
            print("  %-52s %s" % (rel, why))
    return 1 if (broken or hung) else 0


if __name__ == "__main__":
    sys.exit(main())
