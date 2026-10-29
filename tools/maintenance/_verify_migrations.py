"""Apply every Flyway migration to a throwaway H2 and fail on any error.

Why this exists
---------------
``V6__llm_quota.sql`` declared a column named ``day``. H2 treats ``DAY`` as a
reserved word (it is the unit in INTERVAL literals), so the script died with
``Syntax error ... expected "identifier"``. Nothing in the repository could see
it:

  * the Java suite runs against Mockito-backed fake repositories -- there is no
    SQL anywhere in it, so it has nothing to say about DDL;
  * ``mvnw package`` puts the .sql into the jar without ever executing it;
  * on a server, Flyway would have recorded V6 as **failed**, and from that
    moment ``flyway_schema_history`` is poisoned: rolling the jar back does
    *not* restore service, because the previous version refuses to start against
    a failed migration.

So the defect was reachable only *after* deployment, and its remedy was not the
documented rollback. That combination is what makes executing the migration text
here -- against the same H2 build the app runs on -- worth a permanent check
rather than a one-off manual test.

What it does NOT cover
----------------------
It validates the **SQL**, not the entity mapping. A ``@Column`` that disagrees
with the DDL still passes here; so does a migration whose statements are
correct but whose ordering breaks a later one in a way only a populated
database would reveal. Those halves are covered by booting the jar against a
scratch database -- see the pre-deploy checklist in
``docs/云端部署与运维说明.md``. Stated explicitly because a check that quietly
overstates its coverage is worse than a narrow one that says so.

Run:  python tools/maintenance/_verify_migrations.py [--self-test]
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _java import JAVA, h2_jar  # noqa: E402

MIGRATIONS = os.path.join(ROOT, "backend-java", "src", "main", "resources", "db", "migration")


def version_key(path):
    """Sort V10 after V9. Lexicographic ordering puts V10 before V9."""
    match = re.match(r"V(\d+)__", os.path.basename(path))
    return int(match.group(1)) if match else -1


def run_script(h2, url, script_path):
    """Execute one .sql file. Returns (returncode, combined output)."""
    proc = subprocess.run(
        [JAVA, "-cp", h2, "org.h2.tools.RunScript",
         "-url", url, "-user", "sa", "-password", "", "-script", str(script_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_sql(h2, url, sql, workdir):
    path = os.path.join(workdir, "probe.sql")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(sql + "\n")
    return run_script(h2, url, path)


def scratch_url(workdir):
    # Forward slashes: a Windows backslash path inside a JDBC URL is read as an
    # escape, and H2 then reports "database not found" for a directory that
    # plainly exists.
    return "jdbc:h2:file:" + os.path.join(workdir, "probe").replace("\\", "/") + ";MODE=MySQL"


def self_test():
    """Show the check can fail.

    Written as a two-sided control against the *actual* defect: a legal DDL must
    be accepted, and the exact declaration that broke V6 must be rejected. If
    only the first half were checked, a RunScript invocation that silently did
    nothing (wrong classpath, wrong URL) would look like a pass.
    """
    h2 = h2_jar()
    if not h2:
        print("self-test FAILED: cannot measure -- no H2 jar")
        return 2
    workdir = tempfile.mkdtemp(prefix="alc-migrate-selftest-")
    try:
        url = scratch_url(workdir)
        good_rc, good_out = run_sql(h2, url, "CREATE TABLE t_ok (quota_day VARCHAR(10) NOT NULL);", workdir)
        bad_rc, bad_out = run_sql(h2, url, "CREATE TABLE t_bad (day VARCHAR(10) NOT NULL);", workdir)
        if good_rc != 0:
            print("self-test FAILED: a legal DDL was rejected, so this check cannot pass:")
            print(good_out.strip()[-500:])
            return 1
        if bad_rc == 0:
            print("self-test FAILED: a reserved-word column name was ACCEPTED -- the check cannot fail")
            return 1
        if "expected" not in bad_out and "Syntax error" not in bad_out:
            print("self-test FAILED: the rejection was not a syntax error, saw:")
            print(bad_out.strip()[-500:])
            return 1
        print("self-test PASSED: legal DDL accepted, reserved-word column rejected")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    if "--self-test" in sys.argv:
        return self_test()

    h2 = h2_jar()
    if not h2:
        print("cannot measure: no H2 jar under ~/.m2/repository/com/h2database/h2")
        return 2
    scripts = sorted(glob.glob(os.path.join(MIGRATIONS, "V*.sql")), key=version_key)
    if not scripts:
        print("cannot measure: no V*.sql under " + MIGRATIONS)
        return 2

    print("H2 driver  : " + h2)
    workdir = tempfile.mkdtemp(prefix="alc-migrate-")
    try:
        url = scratch_url(workdir)
        for path in scripts:
            name = os.path.basename(path)
            code, out = run_script(h2, url, path)
            if code != 0:
                print("FAIL %s" % name)
                # The tail carries the actual SQL and the caret pointing at the
                # offending token; the head is only a stack trace.
                print(out.strip()[-1500:])
                return 1
            print("ok   %s" % name)
        print("scripts applied: %d" % len(scripts))
        print("migration check -- ok")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
