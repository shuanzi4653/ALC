"""Prove the daily quota end-to-end against a real, freshly-migrated database.

Why this exists
---------------
`_verify_migrations.py` executes the migration SQL, but it cannot see whether the
JPA entity agrees with the table. That gap is not hypothetical: it is the same
shape as the `day` defect one layer up, and the entity is the only place where
``quotaDay``/``quota_key``/``used`` are mapped to columns. A unit test cannot
close it either -- the Java suite mocks the repository, so no SQL and no column
name ever reaches a database.

This probe closes it the only way that actually works: start the packaged jar
against a throwaway H2 (Flyway applies V1..V6 for real, Hibernate maps the
entity for real), then drive the endpoints and read the counters back.

It also runs the whole quota judgement **without spending a single LLM call**,
by starting the app with ``--quota.workspace-per-day=1 --quota.ip-per-day=2``:

  * a first call is admitted          -> counter moves
  * a second call from the same workspace is refused with 429/workspace
  * a call from a *fresh* workspace is refused with 429/ip   <- the backstop
  * a fresh workspace's own counter is still 0 while the shared ip counter is 1

The last two are the ones worth having: the first shows the workspace dimension
is per-workspace, the second shows workspace rotation does not buy a new
allowance. Neither depends on reaching DeepSeek -- the filter runs before the
controller, so a 500 from the (absent) Python service is irrelevant to what is
being measured.

Run:  python tools/probes/_probe_quota_local.py
Exits 0 pass, 1 measured-and-broken, 2 could not measure.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, version  # noqa: E402
from _java import JAVA  # noqa: E402

JAR = os.path.join(ROOT, "backend-java", "target", "tianchuang-server-%s.jar" % version())
WS_A = "probe-aaaaaa"
WS_B = "probe-bbbbbb"
WS_C = "probe-cccccc"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http(method, url, workspace=None, payload=None):
    """Returns (status, parsed-json-or-None). Never raises on an HTTP error status."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if workspace:
        request.add_header("X-ALC-Workspace", workspace)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body.strip().startswith("{") else None)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(body)
        except ValueError:
            return error.code, None


def wait_ready(base, proc, seconds=150):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            status, _ = http("GET", base + "/api/quota", WS_A)
            if status == 200:
                return True
        except OSError:
            pass
        time.sleep(1.0)
    return False


def used_of(status_body, dimension):
    """None when the dimension does not apply -- NOT 0.

    Distinguishing "absent" from "zero" is the point: rendering the first as 0
    would claim the workspace dimension is protecting a caller who is in fact
    only covered by the ip dimension.
    """
    section = (status_body or {}).get(dimension) or {}
    return section.get("used") if section.get("present") else None


def main():
    if not os.path.isfile(JAR):
        print("cannot measure: no jar at " + JAR)
        return 2

    workdir = tempfile.mkdtemp(prefix="alc-quota-probe-")
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    url = "jdbc:h2:file:" + os.path.join(workdir, "quota").replace("\\", "/") + ";MODE=MySQL"
    log_path = os.path.join(workdir, "boot.log")
    findings = []

    print("jar    : " + JAR)
    print("port   : %d" % port)
    print("H2     : " + url)
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [JAVA, "-jar", JAR,
             "--server.port=%d" % port,
             "--spring.datasource.url=" + url,
             "--quota.workspace-per-day=1",
             "--quota.ip-per-day=2"],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    try:
        if not wait_ready(base, proc):
            print("cannot measure: the service never became ready; boot log tail:")
            print(_tail(log_path, 25))
            return 2

        # --- 1. a fresh workspace starts at zero and says so -----------------
        status, body = http("GET", base + "/api/quota", WS_A)
        if status != 200:
            findings.append("GET /api/quota returned %s" % status)
        if used_of(body, "workspace") != 0:
            findings.append("fresh workspace should read used=0, got %r" % used_of(body, "workspace"))
        if used_of(body, "ip") != 0:
            findings.append("fresh ip should read used=0, got %r" % used_of(body, "ip"))
        if (body or {}).get("workspace", {}).get("limit") != 1:
            findings.append("--quota.workspace-per-day=1 did not reach the app: %r"
                            % (body or {}).get("workspace"))
        print("boot ok; fresh workspace reports used=%r limit=%r"
              % (used_of(body, "workspace"), (body or {}).get("workspace", {}).get("limit")))

        # --- 2. an unidentified caller must read "absent", not 0 -------------
        status, anon = http("GET", base + "/api/quota", None)
        if (anon or {}).get("workspace", {}).get("present") is not False:
            findings.append("unidentified caller should report workspace present=false, got %r"
                            % (anon or {}).get("workspace"))
        elif "used" in (anon or {}).get("workspace", {}):
            findings.append("unidentified caller must NOT report used=0 -- absent is not zero")

        # --- 3. first admitted call moves BOTH dimensions by one ------------
        status, _ = http("POST", base + "/api/agent/ask", WS_A, {"question": "probe"})
        print("call 1 (ws A) -> HTTP %s (5xx expected: the Python service is not running)" % status)
        status, body = http("GET", base + "/api/quota", WS_A)
        if used_of(body, "workspace") != 1:
            findings.append("after one call the workspace counter should be 1, got %r"
                            % used_of(body, "workspace"))
        if used_of(body, "ip") != 1:
            findings.append("after one call the ip counter should be 1, got %r" % used_of(body, "ip"))

        # --- 4. same workspace again: refused by the WORKSPACE dimension ----
        status, body = http("POST", base + "/api/agent/ask", WS_A, {"question": "probe"})
        if status != 429:
            findings.append("second call from the same workspace should be 429, got %s" % status)
        if (body or {}).get("dimension") != "workspace":
            findings.append("second call should be refused by 'workspace', got %r"
                            % (body or {}).get("dimension"))
        print("call 2 (ws A) -> HTTP %s dimension=%r" % (status, (body or {}).get("dimension")))

        # --- 5. a FRESH workspace: refused by the IP dimension --------------
        # This is the assertion a workspace-only quota cannot pass: a brand-new
        # workspace has a brand-new workspace allowance, so only the ip cap can
        # stop it.
        status, body = http("POST", base + "/api/agent/ask", WS_B, {"question": "probe"})
        print("call 3 (ws B) -> HTTP %s dimension=%r" % (status, (body or {}).get("dimension")))
        if status == 429:
            findings.append("ws B had its own allowance (ip was only 1/2), it should be admitted")
        status, body = http("POST", base + "/api/agent/ask", WS_C, {"question": "probe"})
        if status != 429 or (body or {}).get("dimension") != "ip":
            findings.append("rotating to a fresh workspace must be refused by 'ip', got %s %r"
                            % (status, (body or {}).get("dimension")))
        print("call 4 (ws C, fresh) -> HTTP %s dimension=%r" % (status, (body or {}).get("dimension")))

        # --- 6. the two dimensions are separate facts -----------------------
        # ws B was admitted, ws C was refused by ip -- so ws B's own counter is
        # 1 while ws C's is 0, yet both share ip=2.
        status, body_b = http("GET", base + "/api/quota", WS_B)
        status, body_c = http("GET", base + "/api/quota", WS_C)
        if used_of(body_b, "workspace") != 1:
            findings.append("ws B should hold 1, got %r" % used_of(body_b, "workspace"))
        if used_of(body_c, "workspace") != 0:
            findings.append("ws C was refused by ip, so its workspace counter must stay 0, got %r"
                            % used_of(body_c, "workspace"))
        print("ws B=%r  ws C=%r  (shared ip=%r)"
              % (used_of(body_b, "workspace"), used_of(body_c, "workspace"), used_of(body_b, "ip")))

        # --- 7. reading quota must not consume quota -------------------------
        status, again = http("GET", base + "/api/quota", WS_B)
        if used_of(again, "workspace") != 1:
            findings.append("GET /api/quota charged the quota: ws B moved to %r"
                            % used_of(again, "workspace"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)

    print()
    if findings:
        for item in findings:
            print("FAIL " + item)
        print("quota probe -- %d finding(s)" % len(findings))
        return 1
    print("quota probe -- ok")
    return 0


def _tail(path, lines):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return "\n".join(handle.read().splitlines()[-lines:])
    except OSError:
        return "(no log)"


if __name__ == "__main__":
    sys.exit(main())
