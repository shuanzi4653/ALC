"""Attribute the 130 s plan to its functions, now that a plan is short enough to profile.

Measured state: seeds 42 / 99999 / 0 all reach READY in 125-141 s for a 7760-flight
fleet.  The 8 s budget in the project notes refers to a 2910-flight fleet and is
therefore not comparable; what matters is where the time goes now.

The band hull was one contributor (9.6x faster took over 292 s down to ~130 s),
which by subtraction is around 160 s of the original cost -- but a subtraction is
an estimate and this profile is the measurement.  It prints only cumulative rows
for functions in the traffic package, so the output is the attribution rather
than a wall of stdlib frames.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_plan_profile.py
"""

import cProfile
import io
import pstats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))


def main():
    from traffic import service

    profiler = cProfile.Profile()
    profiler.enable()
    result = service.simulate(seed=0, scenario='nominal')
    profiler.disable()

    flights = len(getattr(result, 'flights', None) or []) if result is not None else -1
    print('simulate(seed=0, nominal) complete; result flights=%s' % flights)
    print()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats('cumulative')
    stats.print_stats()
    text = stream.getvalue()

    # Keep only frames from the project itself, so the output is the attribution.
    lines = [line for line in text.splitlines()
             if 'traffic' in line or 'weather' in line or 'spatial' in line
             or line.startswith('ncalls') or line.startswith('   Ordered')]
    print('--- cumulative, project frames only (top 30) ---')
    for line in lines[:36]:
        print(line)
    print()

    # The self-time view answers "what is the leaf that actually burns CPU".
    stream2 = io.StringIO()
    stats2 = pstats.Stats(profiler, stream=stream2).sort_stats('tottime')
    stats2.print_stats()
    text2 = stream2.getvalue()
    lines2 = [line for line in text2.splitlines()
              if 'traffic' in line or line.startswith('ncalls')]
    print('--- tottime (self), project frames only (top 25) ---')
    for line in lines2[:31]:
        print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
