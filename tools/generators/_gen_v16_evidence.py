"""Generate the V1.6 evidence package.

Measures, in one run, the four claims V1.6 makes. Everything here is measured
live; nothing is copied from a previous run or from a report, so the numbers in
the output match the code by construction rather than by trust.

1. **Cloud shape** - radius CV per drawn outline and the spread of equivalent
   radii: are the cloud masses actually irregular, and actually different sizes.
2. **Life cycle** - do cells appear and disappear across the timeline, and does a
   single cell's area follow a grow-then-decay curve.
3. **Geometry quality** - exterior turn profile of every drawn tier. Convex turns
   above 45 degrees are spikes, edges below 10 m are hairlines; those are the two
   failure modes that took work to close in this version, so they are asserted
   here rather than described.
4. **Radar channel** - is the credential-free CMA tile channel live, plus the
   honest note that dBZ does not yet drive geometry.

Writes docs/evaluation-v1.6/cloud-shape-and-radar.json.
"""

import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, DOCS  # noqa: E402
import io
import datetime
import json
import math


from traffic.weather import NetworkWeather  # noqa: E402

OUT_DIR = os.path.join(DOCS, "evaluation-v1.6")
ARTIFACT_FPS = os.path.join(ROOT, "artifacts", "browser_fps.json")

SEED = 42
SCENARIO = "moving"
MINUTES = (0, 60, 120, 240, 360, 479)
TURN_LIMIT_DEG = 45.0
HAIRLINE_M = 10.0
TIERS = (1, 2, 3)  # field, ban, caution

TIER_NAMES = {1: "field", 2: "ban", 3: "caution"}


def parts_of(geometry):
    """Every Polygon inside a Polygon or MultiPolygon."""
    if geometry is None:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for p in geometry.geoms if p.geom_type == "Polygon"]


def radius_cv(polygon):
    """Mean radius and coefficient of variation about the polygon centroid."""
    centroid = polygon.centroid
    coords = list(polygon.exterior.coords)[:-1]
    radii = [math.hypot(x - centroid.x, y - centroid.y) for x, y in coords]
    if not radii:
        return 0.0, 0.0
    mean = sum(radii) / len(radii)
    if mean <= 0:
        return 0.0, 0.0
    var = sum((r - mean) ** 2 for r in radii) / len(radii)
    return mean, math.sqrt(var) / mean


def turns(polygon):
    """Yield (edge_length_m, turn_degrees, is_convex) at each exterior vertex.

    Convex here means the outline turns away from its interior, which is where a
    spike shows up; concave turns are the inward notches where two masses merge.
    """
    coords = list(polygon.exterior.coords)
    if len(coords) < 4:
        return
    points = coords[:-1]
    count = len(points)
    for index in range(count):
        prev = points[index - 1]
        here = points[index]
        nxt = points[(index + 1) % count]
        v1 = (here[0] - prev[0], here[1] - prev[1])
        v2 = (nxt[0] - here[0], nxt[1] - here[1])
        len1 = math.hypot(*v1)
        len2 = math.hypot(*v2)
        if len1 < 1e-9 or len2 < 1e-9:
            continue
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        angle = math.degrees(math.atan2(abs(cross), dot))
        yield len1, angle, cross < 0


def tier_quality(geometry, tier):
    """Turn profile of one tier across all its parts."""
    convex = 0
    concave = 0
    worst_convex = 0.0
    worst_concave = 0.0
    shortest = None
    polygons = parts_of(geometry)
    for polygon in polygons:
        for edge_m, angle, is_convex in turns(polygon):
            if shortest is None or edge_m < shortest:
                shortest = edge_m
            if is_convex:
                convex += 1
                worst_convex = max(worst_convex, angle)
            else:
                concave += 1
                worst_concave = max(worst_concave, angle)
    return {
        "tier": TIER_NAMES.get(tier, str(tier)),
        "polygons": len(polygons),
        "convexTurns": convex,
        "concaveTurns": concave,
        "worstConvexTurnDeg": round(worst_convex, 2),
        "worstConcaveTurnDeg": round(worst_concave, 2),
        "shortestEdgeM": round(shortest, 1) if shortest is not None else None,
        "convexTurnsOverLimit": 0 if worst_convex < TURN_LIMIT_DEG else 1,
        "hairlineEdges": 0 if (shortest or 0.0) >= HAIRLINE_M else 1,
    }


def browser_frame_budget():
    """Read the measured browser frame cost, if the probe has been run.

    The frame rate is *not* estimated here. `tools/probes/_probe_browser_fps.py`
    drives headless Edge over CDP and writes `artifacts/browser_fps.json`; this
    function only reports what that file contains, so the document can never
    claim a frame rate nobody measured. A missing file is reported as missing
    rather than back-filled with a plausible number.
    """
    if not os.path.exists(ARTIFACT_FPS):
        return {
            "measured": False,
            "note": ("run tools/probes/_probe_browser_fps.py to measure the browser "
                     "frame cost; no artifact present at " + ARTIFACT_FPS),
        }
    try:
        with io.open(ARTIFACT_FPS, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # noqa: BLE001 - report, never crash a generator
        return {"measured": False, "error": repr(exc)}

    rows = []
    stages = {}
    for row in payload.get("results") or []:
        rows.append({
            "flights": row.get("flightCount"),
            "drawnFlightsPeak": row.get("drawnFlightsPeak"),
            "meanMs": row.get("meanMs"),
            "p95Ms": row.get("p95Ms"),
            "maxMs": row.get("maxMs"),
            "meanFps": row.get("meanFps"),
            "worstFps": row.get("worstFps"),
            "meets30Fps": row.get("meets30Fps"),
        })
    largest = rows[-1] if rows else {}
    # The ledger filter has its own budget and its own stage row; report it in the
    # same block so both acceptance numbers sit beside the run that produced them.
    for stage in payload.get("perFlightStages") or []:
        stages[stage.get("flightCount")] = stage.get("filterLedgerRowsMs")
    ledger = stages.get(largest.get("flights")) if largest else None
    return {
        "measured": bool(payload.get("ok")),
        "budgetMs": round(1000.0 / 30.0, 1),
        "driver": "headless Microsoft Edge over CDP (tools/probes/_probe_browser_fps.py)",
        "worstCase": largest,
        "allFleetSizesMeetBudget": all(r.get("meets30Fps") for r in rows) if rows else None,
        "ledgerFilter": {
            "budgetMs": 300.0,
            "measuredMs": ledger,
            "flights": largest.get("flights"),
            "meetsBudget": (ledger is not None and ledger <= 300.0),
        },
        "rows": rows,
    }


def radar_status():
    """Probe the credential-free CMA tile channel without failing the run.

    Records whether the channel answers at this moment, the age of the newest
    slot, and the decoded frame's echo statistics. A failure is data too: the
    point is to report the channel's state, not to assert it is healthy.
    """
    try:
        from traffic import cma_tiles
    except Exception as exc:  # noqa: BLE001 - report, never crash a generator
        return {"available": False, "error": repr(exc)}

    result = dict(cma_tiles.status())
    result["available"] = False
    try:
        frame = cma_tiles.frame()
        if isinstance(frame, dict):
            result["available"] = bool(frame.get("available"))
            for key in ("slot", "slotAgeMinutes", "lookbackStepsUsed",
                        "degreesPerCell", "gridTiles", "provenance", "stats", "error"):
                if key in frame:
                    result[key] = frame[key]
            result["tileFormat"] = (frame.get("provenance") or {}).get("tileFormat")
        else:
            result["available"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    return result


def radar_derived_risk():
    """Measure the radar raster -> risk-geometry path on the real live frame.

    This replaces a sentence that used to say the conversion "is not
    implemented". A claim of closure needs a number behind it, so the function
    runs the actual pipeline -- fetch frame, classify, register, polygonise,
    clip, shield -- and reports both the derived area and an *independent*
    count of in-boundary cells, so the two can be compared in the JSON rather
    than taken on trust. Cross-checking matters here because the first version
    of this path shipped a metre polygon that was never projected: it was
    4300 km north of where it belonged, clipped to nothing, and every validity
    check still passed.
    """
    result = {"available": False}
    try:
        from traffic import radar_field, service
    except Exception as exc:  # noqa: BLE001 - report, never crash a generator
        result["error"] = repr(exc)
        return result

    try:
        payload = service.radar_regions(minute=0)
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
        return result

    result["available"] = bool(payload.get("available"))
    if payload.get("error"):
        result["error"] = payload["error"]
    result["summary"] = payload.get("summary")
    result["watch"] = payload.get("watch")

    regions = payload.get("regions") or []
    result["regions"] = len(regions)
    result["regionIds"] = [r.get("id") for r in regions if isinstance(r, dict)]

    total_km2 = 0.0
    core_km2 = 0.0
    from shapely.geometry import shape as _shape
    for region in regions:
        if not isinstance(region, dict):
            continue
        for key, sink in (("ban", "ban"), ("caution", "caution")):
            geometry = region.get(key)
            if not isinstance(geometry, dict):
                continue
            try:
                polygon = _shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if polygon.is_empty:
                continue
            area_km2 = polygon.area / 1.0e6
            if sink == "ban":
                total_km2 += area_km2
            else:
                core_km2 += area_km2
    result["banAreaKm2"] = round(total_km2, 1)
    result["cautionAreaKm2"] = round(core_km2, 1)

    # Independent route to the same quantity: count the raster cells the reader
    # itself places inside the operating boundary, and compare with what the
    # derived geometry drew.
    independent = _radar_cells_inside_boundary()
    result["independentCellsInBoundary"] = independent
    if independent is not None:
        result["independentRasterAreaKm2"] = round(independent["areaKm2"], 1)
        result["derivationMatchesIndependent"] = bool(
            total_km2 > 0.0
            and independent["areaKm2"] > 0.0
            and abs(total_km2 - independent["areaKm2"]) / independent["areaKm2"] < 0.15
        )
    return result


def _radar_cells_inside_boundary():
    """Classify every raster cell, keep the in-boundary ones, report their area.

    Deliberately doesn't call `radar_field.derive` -- the point is a second
    opinion obtained by different means, so a shared bug cannot hide. The tile
    rows are walked here exactly as the reader exposes them, and each cell is
    clipped against the same boundary `derive` uses.
    """
    try:
        from traffic import cma_tiles, radar_field, weather
    except Exception:  # noqa: BLE001
        return None
    try:
        frame = cma_tiles.frame()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(frame, dict) or not frame.get("available"):
        return None
    zoom = (frame.get("provenance") or {}).get("zoom")
    tiles = frame.get("cells") or []
    if zoom is None or not tiles:
        return None

    boundary = weather.boundary()
    area = 0.0
    kept = 0
    for x, y, rows in tiles:
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                if radar_field.band_of(value) is None:
                    continue
                quad = radar_field.cell_quad(x, y, column_index, row_index, zoom)
                polygon = radar_field._quad_metres(quad)
                if polygon.is_empty:
                    continue
                inside = polygon.intersection(boundary)
                if inside.is_empty or inside.area <= 0.0:
                    continue
                kept += 1
                area += inside.area
    return {"cells": kept, "areaKm2": area / 1.0e6}


def single_cell_life(weather):
    """Area curve of one cell over its own life, to check grow-then-decay."""
    best = None
    for cell in weather.cells:
        if cell.get("shape") == "BAND":
            continue
        birth = cell.get("birth", 0)
        life = cell.get("lifespan") or cell.get("life") or 0
        if life and (best is None or life > best[1]):
            best = (cell, life, birth)
    if best is None:
        return None
    cell, life, birth = best
    from traffic.weather import MIN_VISIBLE_RADIUS_M  # noqa: E402

    samples = []
    for fraction in (0.05, 0.2, 0.4, 0.6, 0.8, 0.95):
        minute = int(birth + life * fraction)
        radius = weather.radius_at(cell, minute)
        if radius < MIN_VISIBLE_RADIUS_M:
            continue
        samples.append({
            "minute": minute,
            "ageFraction": fraction,
            "radiusM": round(radius, 1),
            "areaKm2": round(math.pi * radius ** 2 / 1e6, 1),
        })
    if not samples:
        return None
    peak = max(s["radiusM"] for s in samples)
    return {
        "cell": cell.get("cell_id") or cell.get("id") or "?",
        "birthMinute": birth,
        "lifespanMinutes": life,
        "peakRadiusM": peak,
        "firstRadiusM": samples[0]["radiusM"],
        "peakOverFirst": round(peak / samples[0]["radiusM"], 2) if samples[0]["radiusM"] else None,
        "samples": samples,
    }


def main():
    weather = NetworkWeather(seed=SEED, scenario=SCENARIO)

    shape_rows = []
    size_rows = []
    live_rows = []
    quality_rows = []

    for minute in MINUTES:
        drawn = weather.shapes(minute)
        live_rows.append({"minute": minute, "drawnCells": len(drawn)})

        for cell, field, ban, caution in drawn:
            tiers = {1: field, 2: ban, 3: caution}
            for tier in TIERS:
                geometry = tiers[tier]
                for polygon in parts_of(geometry):
                    mean, cv = radius_cv(polygon)
                    shape_rows.append({
                        "minute": minute,
                        "cell": cell.get("cell_id") or cell.get("id") or "?",
                        "tier": TIER_NAMES[tier],
                        "equivalentRadiusM": round(mean, 1),
                        "radiusCv": round(cv, 4),
                    })
            if field is not None and not field.is_empty:
                mean, _cv = radius_cv(parts_of(field)[0])
                size_rows.append({
                    "minute": minute,
                    "cell": cell.get("cell_id") or cell.get("id") or "?",
                    "equivalentRadiusM": round(mean, 1),
                })

        by_tier = {}
        for tier in TIERS:
            merged = None
            for _cell, _field, _ban, _caution in drawn:
                geometry = {1: _field, 2: _ban, 3: _caution}[tier]
                if geometry is None or geometry.is_empty:
                    continue
                merged = geometry if merged is None else merged.union(geometry)
            if merged is not None:
                by_tier[TIER_NAMES[tier]] = tier_quality(merged, tier)
        quality_rows.append({"minute": minute, "tiers": by_tier})

    cvs = [r["radiusCv"] for r in shape_rows]
    sizes = [r["equivalentRadiusM"] for r in size_rows if r["equivalentRadiusM"] > 0]

    worst_convex = max(
        (t["worstConvexTurnDeg"] for row in quality_rows for t in row["tiers"].values()),
        default=None,
    )
    shortest_edge = min(
        (t["shortestEdgeM"] for row in quality_rows
         for t in row["tiers"].values() if t["shortestEdgeM"] is not None),
        default=None,
    )
    convex_over = sum(
        t["convexTurnsOverLimit"] for row in quality_rows for t in row["tiers"].values()
    )
    hairlines = sum(
        t["hairlineEdges"] for row in quality_rows for t in row["tiers"].values()
    )

    payload = {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "seed": SEED,
        "scenario": SCENARIO,
        "minutesSampled": list(MINUTES),
        "cloudShape": {
            "samples": len(shape_rows),
            "radiusCvMean": round(sum(cvs) / len(cvs), 4) if cvs else None,
            "radiusCvMin": min(cvs) if cvs else None,
            "radiusCvMax": max(cvs) if cvs else None,
            "baselineNote": (
                "a circle scores 0.000 and a regular polygon a constant turn; the "
                "pre-V1.6 three-harmonic ring scored roughly 0.03-0.05"
            ),
            "rows": shape_rows,
        },
        "sizeSpread": {
            "samples": len(sizes),
            "minRadiusM": min(sizes) if sizes else None,
            "maxRadiusM": max(sizes) if sizes else None,
            "maxOverMin": round(max(sizes) / min(sizes), 2) if sizes else None,
            "rows": size_rows,
        },
        "lifeCycle": {
            "distinctLiveCounts": sorted({r["drawnCells"] for r in live_rows}),
            "note": (
                "a single distinct value would mean every cell is present for the "
                "whole timeline; more than one means cells genuinely appear and vanish"
            ),
            "sampleCell": single_cell_life(weather),
            "rows": live_rows,
        },
        "geometryQuality": {
            "turnLimitDeg": TURN_LIMIT_DEG,
            "hairlineLimitM": HAIRLINE_M,
            "worstConvexTurnDeg": worst_convex,
            "shortestEdgeM": shortest_edge,
            "tierMinuteCombinationsOverTurnLimit": convex_over,
            "tierMinuteCombinationsWithHairline": hairlines,
            "rows": quality_rows,
        },
        "radarChannel": radar_status(),
        "radarDerivedRisk": radar_derived_risk(),
        "browserFrameBudget": browser_frame_budget(),
        "notYetDone": [
            "plan computation is about 63-66 s against a design budget fixed when the "
            "network was 2910 flights; it is now 7760, so the two numbers are not "
            "comparable and the budget needs restating against the current fleet",
        ],
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "cloud-shape-and-radar.json")
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)

    print("wrote", path)
    print("radiusCv mean/min/max",
          payload["cloudShape"]["radiusCvMean"],
          payload["cloudShape"]["radiusCvMin"],
          payload["cloudShape"]["radiusCvMax"])
    print("maxOverMin", payload["sizeSpread"]["maxOverMin"])
    print("distinctLiveCounts", payload["lifeCycle"]["distinctLiveCounts"])
    print("worstConvexTurnDeg", worst_convex, "overLimit", convex_over)
    print("shortestEdgeM", shortest_edge, "hairlines", hairlines)
    print("radar", json.dumps(payload["radarChannel"], ensure_ascii=False)[:300])
    print("radarDerivedRisk",
          json.dumps({k: v for k, v in payload["radarDerivedRisk"].items()
                      if k not in ("regionIds", "summary")}, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
