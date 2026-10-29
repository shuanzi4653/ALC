import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, FRONTEND, artifact  # noqa: E402
from _node import NODE  # noqa: E402
import subprocess, json, io

FE = os.path.join(ROOT, "frontend")
PY = os.path.join(ROOT, "backend-python", ".venv", "Scripts", "python.exe")
JAVA = os.path.join(ROOT, "backend-java")
# Through artifact(), not os.path.join(ROOT, ...): this report is a generated
# artefact like every other one, and hard-coding the root is the exact habit
# `_repo.artifact()` exists to remove. Writing it to the root also meant the file
# survived in the working tree after a run, so it read as a stray untracked file
# rather than as output -- and every reader that looked in artifacts/ missed it.
LOG = artifact("verify_out.txt")

lines = []
def say(t):
    lines.append(t)

def run(label, args, cwd, env=None, tail=5000):
    say("=" * 70)
    say(label)
    say("=" * 70)
    p = subprocess.run(args, cwd=cwd, capture_output=True,
                       encoding="utf-8", errors="replace", env=env)
    out = (p.stdout or "") + (p.stderr or "")
    say(out[-tail:] if len(out) > tail else out)
    say("[exit %s]" % p.returncode)
    return p.returncode

results = {}
# cwd for both frontend steps is FE, not ROOT: `frontend/node_modules` is the
# only node_modules in the tree, and running vite with cwd=ROOT resolves it as
# ROOT/node_modules/vite/bin/vite.js, which does not exist. `node --test` given
# no path arguments discovers the suite relative to the cwd, so pinning the cwd
# also keeps `backups/*/frontend/tests/` (archived copies with no node_modules,
# which fail with ERR_MODULE_NOT_FOUND on `import 'vue'`) out of the run.
FE_TESTS = os.path.join(FE, "tests")
FE_TEST_FILES = sorted(
    os.path.join(FE_TESTS, name) for name in os.listdir(FE_TESTS)
    if name.endswith(".test.mjs")
)
results["frontendTests"] = run("FRONTEND TESTS", [NODE, "--test", *FE_TEST_FILES],
                               FE, tail=1800)
results["frontendBuild"] = run("VITE BUILD", [
    NODE, os.path.join(FE, "node_modules", "vite", "bin", "vite.js"), "build"], FE, tail=1500)
results["pythonTests"] = run("PYTHON TESTS", [
    PY, "-m", "pytest", "tests", "-q", "--basetemp=" + os.path.join(ROOT, "_pytest_tmp")],
    os.path.join(ROOT, "backend-python"), tail=2500)

java_env = dict(os.environ)
java_env["JAVA_HOME"] = r"C:\Users\12921\.jdks\ms-17.0.19"
java_env["PATH"] = os.path.join(java_env["JAVA_HOME"], "bin") + os.pathsep + java_env.get("PATH", "")
results["javaTests"] = run("JAVA TESTS", ["cmd", "/c", "mvnw.cmd", "-o", "-B", "test"], JAVA,
                           env=java_env, tail=5000)

say("")
say("SUMMARY " + json.dumps(results))
with io.open(LOG, "w", encoding="utf-8") as h:
    h.write("\n".join(lines))
print(json.dumps(results))
