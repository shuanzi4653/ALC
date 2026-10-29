"""Profile the fixed-zone integration to find the regression."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import cProfile
import pstats
from pathlib import Path


from traffic import service  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io


profiler = cProfile.Profile()
profiler.enable()
service.simulate(seed=42, scenario='clear')
profiler.disable()

stream = io.StringIO()
stats = pstats.Stats(profiler, stream=stream).sort_stats('cumulative')
stats.print_stats(28)
print(stream.getvalue())
