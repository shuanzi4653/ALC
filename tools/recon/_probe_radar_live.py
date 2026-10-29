"""Probe the CMA radar tile channel end to end and print one frame's statistics.

Recon script. Read-only against the network, writes nothing.

Reported: the newest available 6-minute slot, the age of that slot, the tile URL
actually fetched, and the echo statistics of the decoded frame. If any step
fails the error is printed rather than raised, so the caller always gets an
answer about whether the channel is live right now.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import statistics
import json
import datetime


from traffic import cma_tiles  # noqa: E402

out = {}

try:
    slot = cma_tiles.latest_slot()
    out["slot"] = str(slot)

    # latest_slot returns a datetime; tile_url wants explicit tile coordinates.
    grid = getattr(cma_tiles, "DEFAULT_GRID", ((6, 2), (6, 3)))
    zoom = getattr(cma_tiles, "DEFAULT_ZOOM", 3)
    out["grid"] = [list(item) for item in grid]
    out["zoom"] = zoom
    first_x, first_y = grid[0]
    out["slotUrl"] = cma_tiles.tile_url(slot, zoom, first_x, first_y)

    now = datetime.datetime.now(datetime.timezone.utc)
    out["observedAt"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # A datetime slot gives the frame age directly.
    try:
        stamp = slot
        if not isinstance(stamp, datetime.datetime):
            stamp = datetime.datetime.strptime(str(slot), "%Y%m%d%H%M")
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=datetime.timezone.utc)
        out["slotAgeMinutes"] = round((now - stamp).total_seconds() / 60.0, 1)
    except Exception as exc:  # noqa: BLE001
        out["slotAgeError"] = repr(exc)

    frame = cma_tiles.frame()
    out["frameType"] = type(frame).__name__
    if isinstance(frame, dict):
        # frame() already reports its own slot, provenance and echo statistics.
        out["frameKeys"] = sorted(frame.keys())
        for key in ("available", "slot", "slotAgeMinutes", "lookbackStepsUsed",
                    "degreesPerCell", "gridTiles", "provenance", "stats", "error"):
            if key in frame:
                out[key] = frame[key]
        rows = frame.get("rows")
    else:
        rows = getattr(frame, "rows", None)

    if rows and "stats" not in out:
        out["stats"] = cma_tiles.sample_stats(rows)
except Exception as exc:  # noqa: BLE001 - a probe reports, it does not explode
    out["error"] = repr(exc)

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
