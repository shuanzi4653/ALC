"""Start the three dev services the way `scripts/dev.ps1` intends.

`dev.ps1` cannot run here: PowerShell refuses `Start-Process` with
"已添加项。字典中的关键字: Path 所添加的关键字: PATH" because this host exports
both `Path` and `PATH`. That is a host quirk, not a project bug, so the fix
belongs here rather than in the project script: normalise the environment to a
single upper-case key and launch with `subprocess`.

Logs are written to `.run/*-dev.{out,err}.log`, matching the script, because the
user cannot see the service windows and those files are the only evidence.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _node import NODE  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import subprocess
import time

RUN = ROOT / '.run'
PYTHON = ROOT / 'backend-python' / '.venv' / 'Scripts' / 'python.exe'
JAVA_HOME = Path(r'C:\Users\12921\.jdks\ms-17.0.19')
JAVA = JAVA_HOME / 'bin' / 'java.exe'
NODE = Path(NODE)  # _node exports str, same convention as _repo
CLASSES = ROOT / 'backend-java' / 'target' / 'classes'
CLASSPATH_FILE = RUN / 'java-classpath.txt'

RUN.mkdir(parents=True, exist_ok=True)

# Collapse the duplicated Path/PATH keys into one; this is the exact condition
# that makes Start-Process throw.
env = {key.upper(): value for key, value in os.environ.items()}
env['JAVA_HOME'] = str(JAVA_HOME)
env['NO_PROXY'] = '127.0.0.1,localhost'
env['no_proxy'] = '127.0.0.1,localhost'

classpath = str(CLASSES) + ';' + CLASSPATH_FILE.read_text(encoding='utf-8').strip()

java_args = [
    str(JAVA), '-cp', classpath, 'com.tianchuang.TianchuangApplication',
    '--server.port=8085', '--server.address=127.0.0.1',
    '--local.source-mode=true', '--push.mail.enabled=false',
    '--push.dingtalk-webhook=', '--push.feishu-webhook=', '--push.wecom-webhook=',
]

specs = [
    ('python', [str(PYTHON), '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8600'],
     ROOT / 'backend-python'),
    ('java', java_args, ROOT),
    ('frontend', [str(NODE), str(ROOT / 'frontend' / 'node_modules' / 'vite' / 'bin' / 'vite.js'),
                  '--host', '127.0.0.1', '--port', '5180', '--strictPort'],
     ROOT / 'frontend'),
]

handles = {}
# Taken **before** the first Popen, and that order matters: the Python service reads
# `VERSION` from disk exactly once, at import time (`decision_service.py`), so the
# moment this process starts is the moment its "generation" is fixed. Recording a
# timestamp from *after* the spawns would open a small window in which a source edit
# stays invisible to the staleness check below.
launched_at = time.time()
for name, command, cwd in specs:
    out = open(RUN / f'{name}-dev.out.log', 'w', encoding='utf-8', errors='replace')
    err = open(RUN / f'{name}-dev.err.log', 'w', encoding='utf-8', errors='replace')
    # CREATE_NEW_PROCESS_GROUP so a later stop can target the tree; the host kills
    # children when this very command returns, so the caller must background it.
    process = subprocess.Popen(command, cwd=str(cwd), env=env, stdout=out, stderr=err,
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    handles[name] = process
    print(f'started {name} pid={process.pid}', flush=True)

state = RUN / 'processes.json'
import json  # noqa: E402

# `launchedAt` is what makes "which generation is this?" answerable downstream.
# Before it existed the file recorded only pids, so a probe could tell that
# *something* was listening but never whether it was started before or after the
# code was last edited -- ISS-0.9.19-04, which had already happened twice.
state.write_text(json.dumps({
    'projectRoot': str(ROOT), 'mode': 'source', 'launchedAt': launched_at,
    'ports': {'java': 8085, 'python': 8600, 'frontend': 5180},
    **{f'{name}Pid': process.pid for name, process in handles.items()},
}, ensure_ascii=False), encoding='utf-8')

# Hold the process alive so the services outlive this command.
deadline = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 900)
try:
    while time.time() < deadline:
        for name, process in handles.items():
            code = process.poll()
            if code is not None:
                print(f'{name} exited early with code {code}', flush=True)
        time.sleep(3)
except KeyboardInterrupt:
    pass
