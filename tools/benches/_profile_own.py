"""Report per-function cost for the project's own modules only.

Third-party frames dominate a flat sort (shapely/numpy internals), which hides
which of *our* functions is responsible. This prints only traffic/ and
weather/ frames, with the total so the share is readable.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import cProfile
import pstats


from traffic import service  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io


service.network()

profiler = cProfile.Profile()
profiler.enable()
service.simulate(seed=42, scenario='moving')
profiler.disable()

stream = io.StringIO()
stats = pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('tottime')
stats.print_stats()
text = stream.getvalue()
total = text.splitlines()[0]

keys = ('service.py', 'spatial.py', 'weather.py', 'routing.py', 'resources.py',
        'zones.py', 'catalog.py', 'airspace.py', 'delivery.py', 'obstacles.py')
rows = [line for line in text.splitlines()
        if any(k in line for k in keys) and 'site-packages' not in line]

out = [total, '', '--- project frames only (tottime desc) ---'] + rows[:40]
report = '\n'.join(out)
Path(ROOT / '_profile_traffic_only.txt').write_text(report, encoding='utf-8')
print(report)
