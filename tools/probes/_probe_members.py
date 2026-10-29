
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
from weather.geometry import boundary
from traffic.weather import NetworkWeather

world = NetworkWeather(42, 'moving')
for minute in (0, 12.4, 45, 70):
    cells = world.shapes(minute)
    regions = world.frame(minute)
    drawable = sorted(cell['id'] for cell, field, _, _ in cells
                      if not field.intersection(boundary()).is_empty)
    members = sorted(source for region in regions for source in region['sources'])
    clipped = {}
    for cell, field, _, _ in cells:
        clipped[cell['id']] = field.intersection(boundary()).is_empty
    print("minute", minute)
    print("  cells", len(cells), "regions", len(regions))
    print("  drawable", len(drawable), drawable)
    print("  members ", len(members))
    extra = [m for m in members if m not in drawable]
    missing = [d for d in drawable if d not in members]
    print("  extra", extra)
    print("  missing", missing)
    empties = [k for k, v in clipped.items() if v]
    print("  clipped-to-empty", empties)
    print()
