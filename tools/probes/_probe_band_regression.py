"""Diagnose the two failing band assertions by measuring, not by reading.

Failure 1: the band's clipped area is 8.2e9 m2 against an assertion of >1e10.
Failure 2: the swept envelope for window (56,70) is 1.98e10 m2 smaller than a
            naive per-vertex sweep.

Both were green at V1.6.2 and red at V1.6.3, so the question is *what changed*.
This probe answers three things the failing assertions do not:

  * is the shortfall caused by clipping to the boundary, or is the raw band
    itself smaller?
  * how many clusters exist at each minute (the assertion runs at t=30)?
  * does the envelope shortfall also exist when the reference is built from the
    *drawable* window rather than from a naive full-sweep?

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_band_regression.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), "backend-python"))

from shapely.geometry import MultiPoint  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from traffic import weather as wx  # noqa: E402
from weather.geometry import boundary, project  # noqa: E402


def main():
    world = wx.NetworkWeather(42, "moving")
    band = next(c for c in world.cells if c["shape"] == "BAND")
    frame = boundary()

    print("== cluster inventory ==")
    print("clusters total      : %d" % len(world._band_clusters))
    for minute in (0, 30, 60, 120, 240, 360, 480):
        alive = [c for c in world._band_clusters
                 if wx._band_cluster_radius(c, minute) > 0.0]
        radii = sorted(wx._band_cluster_radius(c, minute) for c in alive)
        print("t=%-4s alive=%-3d radius min/med/max = %s / %s / %s" % (
            minute, len(alive),
            int(radii[0]) if radii else 0,
            int(radii[len(radii) // 2]) if radii else 0,
            int(radii[-1]) if radii else 0))

    print()
    print("== failure 1: band area at t=30 ==")
    for cell, field, ban, caution in world.shapes(30):
        if cell["id"] != "WX-NORTHEAST-BAND":
            continue
        clipped = field.intersection(frame)
        print("raw field area      : %,.0f km2".replace(",", "") % (field.area / 1e6))
        print("clipped area        : %.0f km2  (assertion wants > 10000)" % (clipped.area / 1e6))
        print("field within frame? : %s" % frame.covers(field))
        parts = wx._polygon_parts(field)
        print("raw part count      : %d" % len(parts))
        print("clipped part count  : %d" % len(wx._polygon_parts(clipped)))
        # How much of the raw field falls outside the frame?
        outside = field.difference(frame)
        print("outside frame       : %.0f km2" % (outside.area / 1e6))

    print()
    print("== failure 2: envelope shortfall for (56,70) ==")
    index = next(i for i, c in enumerate(world.cells) if c["shape"] == "BAND")
    cell = world.cells[index]
    for start_bin, end_bin in ((0, 18), (56, 70), (0, 96), (12, 107)):
        coords = [(x, y) for part in wx._polygon_parts(cell["polygon"])
                  for x, y in part.exterior.coords]
        points = []
        for tick in range(start_bin, end_bin + 1):
            dx, dy = world.drift(cell, tick * 5)
            points.extend((px + dx, py + dy) for px, py in coords)
        # Reference A: the test's own construction -- t=0 outline translated.
        ref_a = MultiPoint(points).convex_hull.buffer(wx.SWEPT_BAND_PAD_M, quad_segs=4)
        got = world._swept_band(index, start_bin, end_bin)
        missing_a = ref_a.difference(got).area
        # Reference B: every cluster's *live* outline across the window, which
        # is what `shapes()` actually draws there.
        live = []
        for cluster in cell.get("clusters", ()):
            for tick in range(start_bin, end_bin + 1):
                dx, dy = world.drift(cell, tick * 5)
                outline, core = wx._band_cluster_outlines(cluster, tick * 5)
                if outline is not None:
                    live.append(wx.affinity.translate(outline, xoff=dx, yoff=dy))
        ref_b = unary_union(live) if live else None
        missing_b = ref_b.difference(got).area if ref_b is not None else float("nan")
        # Reference C: the union of *drawn* shapes in this window (ground truth
        # for "is anything the user can see outside the envelope").
        drawn = []
        for tick in range(start_bin, end_bin + 1):
            for c, field, ban, caution in world.shapes(tick * 5):
                if c["shape"] == "BAND":
                    drawn.append(field)
        ref_c = unary_union(drawn) if drawn else None
        missing_c = ref_c.difference(got).area if ref_c is not None else float("nan")
        print("window (%3d,%3d)  naive_ref missing=%14.0f m2 | "
              "live_clusters missing=%14.0f m2 | drawn missing=%14.0f m2"
              % (start_bin, end_bin, missing_a, missing_b, missing_c))

    print()
    print("== is the t=0 polygon representative of t=30? ==")
    t0 = wx._polygon_parts(cell["polygon"])
    print("stored polygon (t=0) centroid: (%.0f, %.0f)" % (cell["polygon"].centroid.x,
                                                          cell["polygon"].centroid.y))
    t30_parts = []
    for c, field, ban, caution in world.shapes(30):
        if c["shape"] == "BAND":
            t30_parts = wx._polygon_parts(field)
    print("t=30 field part count: %d" % len(t30_parts))


if __name__ == "__main__":
    main()
