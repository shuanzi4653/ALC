"""Run the Java test suite with the JDK the project expects.

pom.xml declares java.version=17 and scripts/dev.ps1 picks the same JDK, so using
anything else here would test a different toolchain than the app runs on. The
local .m2 already holds the dependencies, so this runs offline.
"""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
JAVA_HOME = Path(r'C:\Users\12921\.jdks\ms-17.0.19')

env = {k.upper(): v for k, v in os.environ.items()}
env['JAVA_HOME'] = str(JAVA_HOME)
env['PATH'] = f'{JAVA_HOME / "bin"}{os.pathsep}{env.get("PATH", "")}'
env['NO_PROXY'] = '127.0.0.1,localhost'

print(f'JAVA_HOME = {JAVA_HOME}', flush=True)
result = subprocess.run(['cmd', '/c', 'mvnw.cmd', '-o', '-B', 'test'],
                        cwd=str(ROOT / 'backend-java'), env=env)
print('RC', result.returncode, flush=True)
sys.exit(result.returncode)
