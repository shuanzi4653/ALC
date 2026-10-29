"""Which JDK to use. One answer, not several.

``tools/runners/_run_java.py`` carried the literal path
``C:\\Users\\12921\\.jdks\\ms-17.0.19``. The JetBrains-managed JDKs live in
patch-suffixed directories, so a reinstall of 17.0.x moves the directory and
that pin dies with ``FileNotFoundError: [WinError 2]`` -- an error that reads
like "maven is missing" or "the build is broken" but is really "the JDK moved".
``tools/shared/_node.py`` already fixed exactly this shape for node; this is the
same fix for the JDK, so there is one resolver instead of N literals.

Resolution order:

  1. ``ALC_JAVA_HOME`` -- explicit override, and a bad override is an **error**,
     not a quiet fallback: falling back would run the very toolchain the caller
     was trying to avoid.
  2. ``<home>/.jdks/ms-*``, **newest first**. The ``ms-`` prefix is the Microsoft
     build the project standardises on; ``pom.xml`` pins ``java.version=17``, and
     sorting newest-first keeps a patch bump from needing an edit here.
  3. ``JAVA_HOME`` -- whatever the caller's shell already selected.
  4. ``java`` on ``PATH``.

``JAVA_HOME`` is resolved at import time and callers print it, so a log says
which JDK actually ran instead of which one was meant to. Note this deliberately
does **not** fall back to a non-``ms-`` JDK: ``~/.jdks`` also holds an
``openjdk-26``, and silently building with 26 would test a different toolchain
than the app runs on -- which is the whole reason this module exists.
"""
import glob
import os
import shutil
import sys

_HOME = os.path.expanduser('~')
JDKS_DIR = os.path.join(_HOME, '.jdks')


def _usable(java_home):
    """A JDK is usable when it actually has ``bin/java`` -- a bare directory is not."""
    if not java_home:
        return None
    candidate = os.path.join(java_home, 'bin', 'java.exe')
    if os.path.isfile(candidate):
        return os.path.normpath(java_home)
    return None


def resolve_java_home():
    """Absolute path of a usable JDK home, or exit with a reason."""
    override = os.environ.get('ALC_JAVA_HOME')
    if override:
        resolved = _usable(override)
        if not resolved:
            sys.exit('ALC_JAVA_HOME points at %s, which has no bin/java.exe' % override)
        return resolved
    for candidate in sorted(glob.glob(os.path.join(JDKS_DIR, 'ms-*')), reverse=True):
        resolved = _usable(candidate)
        if resolved:
            return resolved
    from_env = _usable(os.environ.get('JAVA_HOME'))
    if from_env:
        return from_env
    java = shutil.which('java')
    if java:
        # PATH gave us an executable, not a home. Derive it so callers that need
        # JAVA_HOME (surefire, mvnw) still work.
        return os.path.dirname(os.path.dirname(os.path.abspath(java)))
    sys.exit('no JDK under %s, no usable JAVA_HOME, and no java on PATH' % JDKS_DIR)


JAVA_HOME = resolve_java_home()
JAVA = os.path.join(JAVA_HOME, 'bin', 'java.exe')
if not os.path.isfile(JAVA):
    JAVA = os.path.join(JAVA_HOME, 'bin', 'java')


def env_with_java(base=None):
    """``base`` (default: this process' environment) plus JAVA_HOME on PATH."""
    env = {k.upper(): v for k, v in (os.environ if base is None else base).items()}
    env['JAVA_HOME'] = JAVA_HOME
    env['PATH'] = os.path.join(JAVA_HOME, 'bin') + os.pathsep + env.get('PATH', '')
    return env


def h2_jar():
    """The H2 driver the app actually runs on, or None.

    Read from the local Maven repository rather than pinned to a version: the
    version is whatever ``spring-boot-starter-parent`` manages, and a literal
    here would go stale on the next Boot upgrade. Newest wins.

    This matters beyond convenience: running a migration against a *different*
    H2 release than production can hide a reserved-word or dialect error, which
    is precisely the defect this helper exists to catch.
    """
    pattern = os.path.join(_HOME, '.m2', 'repository', 'com', 'h2database', 'h2', '*', 'h2-*.jar')
    jars = [j for j in glob.glob(pattern)
            if not j.endswith('-sources.jar') and not j.endswith('-javadoc.jar')]
    if not jars:
        return None
    # Sort by version tuple so 2.3.232 > 2.2.224 (lexicographic gets this wrong
    # for 2.10 vs 2.9).
    def version_key(path):
        stem = os.path.basename(path)[len('h2-'):-len('.jar')]
        parts = []
        for chunk in stem.split('.'):
            parts.append(int(chunk) if chunk.isdigit() else -1)
        return parts

    return sorted(jars, key=version_key)[-1]
