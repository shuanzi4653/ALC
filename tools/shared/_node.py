"""Which node runtime to use. One answer, not seven.

Six scripts each carried the literal path
``C:\\Users\\...\\node\\versions\\22.22.2-3\\node.exe``. The managed runtime is
reinstalled under a **new patch-suffixed directory** every time it is updated,
so that pin went stale and all of them died with ``FileNotFoundError:
[WinError 2]`` -- an error that reads like "vite is missing" or "the build is
broken" but is really "node is missing". One of them also silently ran on a
different interpreter than intended, which is worse than failing.

The fix is not six fresh literals. Resolution happens in **one** place:

  1. ``ALC_NODE`` -- an explicit override, and a bad override is an **error**,
     not a quiet fallback: falling back would run the very interpreter the
     caller was trying to avoid.
  2. The managed installs under ``~/.workbuddy/binaries/node/versions/*/``,
     **newest first**, so a patch bump needs no edit here.
  3. Whatever is on ``PATH``.

``NODE`` is resolved at import time. Callers print it, so a log says which node
actually ran instead of which one was meant to.
"""
import glob
import os
import shutil
import sys

_HOME = os.path.expanduser('~')
VERSIONS_DIR = os.path.join(_HOME, '.workbuddy', 'binaries', 'node', 'versions')
# Where the managed workspace keeps its shared `node_modules`. It is not a
# version directory, so it is not a fallback -- it is a second, independent fact
# about the same managed install.
WORKSPACE_MODULES = os.path.join(_HOME, '.workbuddy', 'binaries', 'node', 'workspace', 'node_modules')


def resolve_node():
    """Absolute path of a usable node executable, or exit with a reason."""
    override = os.environ.get('ALC_NODE')
    if override:
        if not os.path.isfile(override):
            sys.exit('ALC_NODE points at %s, which does not exist' % override)
        return override
    for candidate in sorted(glob.glob(os.path.join(VERSIONS_DIR, '*', 'node.exe')), reverse=True):
        if os.path.isfile(candidate):
            return candidate
    found = shutil.which('node')
    if found:
        return found
    sys.exit('no node runtime under %s and none on PATH' % VERSIONS_DIR)


NODE = resolve_node()
NODE_PATH = WORKSPACE_MODULES
