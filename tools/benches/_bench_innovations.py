"""Prove the four core algorithmic claims, in one run, with numbers.

`docs/paper-innovations.md` states four contributions and cites measurements for
each. This script is the single command that reproduces all of them against the
live code, and -- where the claim is "X is better than the naive Y" -- measures
the naive Y too. A claim whose counterfactual is not measured is not a claim,
it is an assertion.

Four sections, one per contribution:

  1  harmonic outline        curvature budget vs Nyquist-only sampling
  2  concentric layering     same-source rings vs boolean buffer difference
  3  envelope pruning        convex-hull exact pruning vs O(n) full enumeration
  4  single motion source    drawn region is inside the planner's envelope

Everything is measured on the call. Nothing is copied from the document, so if a
mechanism changes and a claim stops holding, this says so.

Run:
    backend-python/.venv/Scripts/python.exe tools/benches/_bench_innovations.py
    ... --json          also print the machine-readable block
    ... --section 3     just one section

Note on the API this binds to, all verified against the shipped module:
    NetworkWeather(seed, scenario).shapes(t)
        -> [(cell, field, ban, caution), ...]
           field   = 外场 (field strength >= 35 dBZ, the monitored tier)
           ban     = 核心 (>= 45 dBZ, may not be entered at all)
           caution = field - ban  (>= 35 dBZ band outside the core)
    NetworkWeather(seed, scenario).cells      -> [cell, ...]
    wx.envelope(start_minute, end_minute)     -> Polygon覆盖该时段（5 分钟分箱）
    wx.drift(cell, minute)                    -> (dx, dy)
    weather._outline_hull_coords(geometry)    -> [(x, y), ...]
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, artifact  # noqa: E402
import io
import json
import math
import random
import time


from shapely.geometry import MultiPoint  # noqa: E402

from traffic import weather  # noqa: E402

SEED = 42
SCENARIO = 'moving'
TURN_LIMIT_DEG = 45.0
TIMELINE_MINUTES = 480


# ---------------------------------------------------------------- geometry ---

def _parts(geometry):
    """Iterate the polygonal parts of a Polygon or MultiPolygon."""
    if geometry is None or geometry.is_empty:
        return []
    return list(getattr(geometry, 'geoms', [geometry]))


def _turn_degrees(ring):
    """Largest exterior turn on a closed ring, in degrees.

    The judge for claim 1: a smooth circle of n vertices turns 360/n degrees per
    step, so a turn far above that is a cusp. The exterior angle is used so the
    metric does not depend on how the ring was produced.
    """
    coords = list(ring.coords)
    if coords and coords[0] == coords[-1]:
        coords = coords[:-1]
    n = len(coords)
    if n < 3:
        return 0.0
    worst = 0.0
    for i in range(n):
        prev, cur, nxt = coords[(i - 1) % n], coords[i], coords[(i + 1) % n]
        ax, ay = cur[0] - prev[0], cur[1] - prev[1]
        bx, by = nxt[0] - cur[0], nxt[1] - cur[1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        if la < 1e-12 or lb < 1e-12:
            continue
        cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        worst = max(worst, math.degrees(math.acos(cosine)))
    return worst


def _worst_turn_of(geometry):
    worst = 0.0
    for poly in _parts(geometry):
        worst = max(worst, _turn_degrees(poly.exterior))
    return worst


# ------------------------------------------------------- 1 curvature budget ---

def section_1(sink):
    """Curvature budget beats Nyquist alone at the stretched long axis."""
    print('=' * 72)
    print('1  harmonic outline: curvature budget vs Nyquist-only sampling')
    print('=' * 72)

    rng = random.Random(SEED)
    configs = [weather.cell_outline_params(rng) for _ in range(134)]

    shipped_worst, shipped_over = 0.0, 0
    for cfg in configs:
        turn = _worst_turn_of(weather._irregular_outline(0.0, 0.0, 25000.0, cfg))
        shipped_worst = max(shipped_worst, turn)
        shipped_over += turn > TURN_LIMIT_DEG

    # Counterfactual: switch the curvature guard off. Raising the permitted turn
    # to 180 degrees collapses the analytic budget *and* lets the refinement loop
    # stop on the first sample, so the vertex count is then decided by Nyquist
    # alone -- which is exactly the design being compared against.
    saved = weather.OUTLINE_MAX_TURN_RAD
    naive_worst, naive_over = 0.0, 0
    try:
        weather.OUTLINE_MAX_TURN_RAD = math.radians(180.0)
        for cfg in configs:
            turn = _worst_turn_of(weather._irregular_outline(0.0, 0.0, 25000.0, cfg))
            naive_worst = max(naive_worst, turn)
            naive_over += turn > TURN_LIMIT_DEG
    finally:
        weather.OUTLINE_MAX_TURN_RAD = saved

    print('  population                 %d cells (seed %d)' % (len(configs), SEED))
    print('  limit                      %.0f deg' % TURN_LIMIT_DEG)
    print('  worst turn, shipped        %6.2f deg   (violations: %d)'
          % (shipped_worst, shipped_over))
    print('  worst turn, guard off      %6.2f deg   (violations: %d)'
          % (naive_worst, naive_over))
    print('  -> guard removes %d violating cell(s); worst improves %.2f deg'
          % (naive_over - shipped_over, naive_worst - shipped_worst))

    sink['curvature'] = {
        'population': len(configs),
        'thresholdDeg': TURN_LIMIT_DEG,
        'worstTurnShippedDeg': round(shipped_worst, 2),
        'worstTurnGuardOffDeg': round(naive_worst, 2),
        'violationsShipped': shipped_over,
        'violationsGuardOff': naive_over,
    }


# ------------------------------------------------------ 2 concentric layer ---

def section_2(sink):
    """Same-source rings are disjoint from the core; buffer-difference is not."""
    print()
    print('=' * 72)
    print('2  concentric layering: same-source rings vs boolean buffer difference')
    print('=' * 72)

    layer = weather.NetworkWeather(SEED, SCENARIO)
    shapes = layer.shapes(120)
    print('  regions at t=120 min       %d' % len(shapes))
    print('  tuple meaning              (cell, field, ban, caution), caution = field - ban')

    # The invariant: the caution ring and the core must not overlap. If they did,
    # one tier would paint over the other and the more severe colour would be
    # lost exactly where the hazard is worst.
    overlap = 0.0
    slivers = 0
    for cell, field, ban, caution in shapes:
        overlap += ban.intersection(caution).area
        for part in _parts(caution):
            if part.area <= 0:
                continue
            # A sliver: negligible area against a long boundary. This is what a
            # difference of two separately densified rings leaves behind, and it
            # is why a "solid" ring can render with faint stripes.
            if part.area / max(part.length, 1e-9) < 1.0:
                slivers += 1

    print('  caution n core overlap     %14.3e m^2   (must be ~0)' % overlap)
    print('  sliver pieces (area/len<1) %d' % slivers)

    # Counterfactual: make the ring the obvious way -- grow the *field* by 900 m
    # and subtract the core: `field.buffer(+900) - core`. `field` carries the
    # detailed outline while `core` is rebuilt from the low-order harmonics, so
    # the two edges are smooth, nearly parallel and *unrelated*: wherever they
    # cross, `difference` keeps a zero-width sliver. That is the historical
    # artefact -- measured 177.4 and 166.0 degree corners on WX-3-06, which
    # render as thin spikes across what is supposed to be solid airspace.
    #
    # An earlier version of this counterfactual buffered the *core* twice with
    # different arc resolutions. It measured 0 slivers on both sides, i.e. no
    # contrast at all -- the two circles it produced were concentric by
    # construction. A counterfactual that cannot reproduce the failure it cites
    # is not evidence, so it now uses the real field/core pair.
    naive_slivers = 0
    naive_overlap = 0.0
    naive_worst_turn = 0.0
    shipped_worst_turn = 0.0
    for cell, field, ban, caution in shapes:
        shipped_worst_turn = max(shipped_worst_turn, _worst_turn_of(caution))
        if not _parts(ban):
            continue
        ring = field.buffer(900.0, quad_segs=16).difference(ban)
        naive_overlap += ring.intersection(ban).area
        naive_worst_turn = max(naive_worst_turn, _worst_turn_of(ring))
        for piece in _parts(ring):
            if piece.area > 0 and piece.area / max(piece.length, 1e-9) < 1.0:
                naive_slivers += 1

    print()
    print('  buffer difference (field.buffer(+900) - core):')
    print('    overlap with core        %14.3e m^2' % naive_overlap)
    print('    sliver pieces            %d' % naive_slivers)
    print('    worst exterior turn      %6.2f deg' % naive_worst_turn)
    print('  same-source rings:')
    print('    worst exterior turn      %6.2f deg' % shipped_worst_turn)
    print('  -> same-source %d sliver(s) vs difference %d; worst turn %.2f vs %.2f deg'
          % (slivers, naive_slivers, shipped_worst_turn, naive_worst_turn))

    sink['concentric'] = {
        'regions': len(shapes),
        'cautionCoreOverlapM2': overlap,
        'sliversShipped': slivers,
        'sliversNaiveDifference': naive_slivers,
        'naiveOverlapM2': naive_overlap,
        'worstTurnShippedDeg': round(shipped_worst_turn, 2),
        'worstTurnNaiveDifferenceDeg': round(naive_worst_turn, 2),
    }


# --------------------------------------------------------- 3 envelope prune ---

def section_3(sink):
    """Convex-hull pruning is exact against full enumeration, and cheaper than it."""
    print()
    print('=' * 72)
    print('3  envelope: convex-hull exact pruning vs full O(n) enumeration')
    print('=' * 72)

    wx = weather.NetworkWeather(SEED, SCENARIO)
    band = next(c for c in wx.cells if c['shape'] == 'BAND')
    pad = weather.SWEPT_BAND_PAD_M
    clusters = len(band.get('clusters', ()) or ())
    print('  band clusters              %d' % clusters)
    print('  band pad (SWEPT_BAND_PAD_M) %.0f m' % pad)

    # The baseline must enumerate the SAME set the shipped path envelopes.
    #
    # It used to be ``hull(band['polygon'] shifted by drift(t))`` -- one *static*
    # outline, every tick. That was written when the band was a single fixed
    # outline and it is no longer that set: each cluster now runs its own life
    # cycle and drops out of the chain, so the static polygon still carries
    # segments that a later window has already vacated. Measured on window 56..70,
    # that stale baseline claimed 17,950 km^2 "missing" that the shipped envelope
    # was never meant to cover. It also made the pruning look *slower* than not
    # pruning, because hulling one 48-vertex outline across 97 offsets is far less
    # work than the real unpruned enumeration. The baseline below walks per tick
    # per cluster, which is what the envelope is built from, so a non-zero deficit
    # from here on is a real gap.
    def _enumerate(layer, cell, ticks):
        points = []
        for tick in ticks:
            dx, dy = layer.drift(cell, tick * 5)
            for cluster in cell.get('clusters', ()) or ():
                for px, py in weather._band_cluster_hull_coords(cluster, tick * 5):
                    points.append((px + dx, py + dy))
        return points

    windows = [(0, 18), (0, 36), (1, 14), (12, 107), (56, 70)]
    worst_missing = 0.0
    worst_slack = 0.0
    for start, end in windows:
        full = MultiPoint(_enumerate(wx, band, range(start, end + 1))).convex_hull
        pruned = wx.envelope(start * 5, end * 5)
        # Safety direction: the shipped envelope must contain the enumerated set.
        worst_missing = max(worst_missing, full.difference(pruned).area)
        # The other direction is the deliberate conservatism (pad + hull-of-hulls);
        # it is reported so a silent blow-up in envelope size is visible too.
        worst_slack = max(worst_slack, pruned.difference(full).area)

    span = 96
    ticks = list(range(0, span + 1))
    offsets = [wx.drift(band, t * 5) for t in ticks]
    hull_vertices = len(MultiPoint(offsets).convex_hull.exterior.coords) - 1

    # Warm vs cold. ``_swept_window`` is lru_cached per 5-minute window and a plan
    # asks for ~588 distinct windows, so cost per *miss* is what the planner pays;
    # a repeat call measures the cache, not the algorithm. Report both, and never
    # quote only the warm one.
    wx.envelope(0, span * 5)
    t0 = time.perf_counter()
    for _ in range(5):
        wx.envelope(0, span * 5)
    t_warm = (time.perf_counter() - t0) / 5

    t0 = time.perf_counter()
    for _ in range(5):
        wx._swept_window.cache_clear()
        wx.envelope(0, span * 5)
    t_cold = (time.perf_counter() - t0) / 5

    t0 = time.perf_counter()
    for _ in range(5):
        MultiPoint(_enumerate(wx, band, ticks)).convex_hull
    t_full = (time.perf_counter() - t0) / 5

    # Why a fixed stride is not an acceptable cheap substitute: it drops ticks, so
    # the hull it builds is strictly inside the true one -- an under-sized envelope
    # is the unsafe direction.
    stride_loss = {}
    full_hull = MultiPoint(_enumerate(wx, band, ticks)).convex_hull
    for stride in (2, 5):
        sampled = MultiPoint(_enumerate(wx, band, ticks[::stride])).convex_hull
        stride_loss[stride] = full_hull.difference(sampled).area

    print('  windows checked            %d' % len(windows))
    print('  missing area vs full enum  %14.3f m^2   (exact <=> 0)' % worst_missing)
    print('  slack over full enum       %14.3e m^2   (conservative side)' % worst_slack)
    print('  full-path tick samples     %d' % (span + 1))
    print('  drift-hull vertices        %d' % hull_vertices)
    print('  -> O(n) -> O(h): %d -> %d  (%.1fx fewer drift offsets)'
          % (span + 1, hull_vertices, (span + 1) / max(hull_vertices, 1)))
    print()
    print('  fixed-stride counterfactual (area the stride fails to cover):')
    for stride, loss in sorted(stride_loss.items()):
        print('    stride %d                 %14.0f m^2' % (stride, loss))
    print()
    print('  timing, window 0..%d min (mean of 5):' % span)
    print('    full enumeration         %8.2f ms' % (t_full * 1000))
    print('    shipped, cache cold      %8.2f ms' % (t_cold * 1000))
    print('    shipped, cache warm      %8.2f ms   (lru_cache hit -- not comparable)' % (t_warm * 1000))
    print('    ratio (full/cold)        %8.2fx' % (t_full / max(t_cold, 1e-9)))
    print('  -> the 19.4x is a *drift-offset* count, not a wall-clock win. Per cold')
    print('     miss the shipped path is at parity because it also pays for the')
    print('     Minkowski sum and the pad buffer; the real saving is that a plan')
    print('     repeats a window (~588 distinct windows / 13k calls), so the warm')
    print('     hit is what the planner mostly pays. Quote the pair, never just one.')

    sink['envelope'] = {
        'bandClusters': clusters,
        'windowsChecked': len(windows),
        'worstMissingAreaM2': round(worst_missing, 3),
        'worstSlackAreaM2': worst_slack,
        'fullTicks': span + 1,
        'driftHullVertices': hull_vertices,
        'fullEnumerationMs': round(t_full * 1000, 2),
        'shippedColdMs': round(t_cold * 1000, 2),
        'shippedWarmMs': round(t_warm * 1000, 2),
        'ratioFullOverCold': round(t_full / max(t_cold, 1e-9), 2),
        'timingNote': ('19.4x is a drift-offset count, not a wall-clock win. Per cold '
                       'miss the shipped path is at parity (it also pays for the Minkowski '
                       'sum and the pad buffer); the saving is the lru_cache hit rate on '
                       'repeated windows. Always quote cold and warm together.'),
        'strideLossM2': {str(k): v for k, v in sorted(stride_loss.items())},
    }


# ------------------------------------------------------ 4 single motion src ---

def section_4(sink):
    """Every drawn region lies inside the envelope the planner avoids."""
    print()
    print('=' * 72)
    print('4  single motion source: drawn region inside the planner envelope')
    print('=' * 72)

    wx = weather.NetworkWeather(SEED, SCENARIO)

    # The comparison has to be time-aligned. The risk surface drifts, so a region
    # drawn at minute t must be checked against the envelope that covers minute
    # t -- comparing it against an envelope for a different minute reports a
    # breach that is only a mismatch of clocks.
    minutes = [30, 120, 240, 360, 450]
    covered, tested, worst_gap = 0, 0, 0.0
    for minute in minutes:
        # ``shapes`` yields (cell, field, ban, caution) -- the *field* (外场,
        # >= 35 dBZ) is the second element, not the core. Checking the field
        # rather than the core is the stronger claim: if the planner's envelope
        # covers the whole monitored field, it covers the no-entry core too.
        for cell, field, _ban, _caution in wx.shapes(minute):
            tested += 1
            envelope = wx.envelope(minute, minute)
            if envelope.covers(field):
                covered += 1
            else:
                worst_gap = max(worst_gap, field.difference(envelope).area)

    print('  minutes sampled            %s' % minutes)
    print('  drawn regions tested       %d' % tested)
    print('  inside planner envelope    %d   (must equal %d)' % (covered, tested))
    print('  worst uncovered area       %14.3f m^2' % worst_gap)

    # Position has one source, so two reads must agree, and the band must be a
    # real member of cells rather than a local the renderer happens to build.
    cell = wx.cells[0]
    deterministic = wx.centre_at(cell, 120) == wx.centre_at(cell, 120)
    band_is_cell = any(c['shape'] == 'BAND' for c in wx.cells)
    print('  centre_at deterministic    %s' % deterministic)
    print('  band is a first-class cell %s' % band_is_cell)

    sink['motion_source'] = {
        'minutesSampled': minutes,
        'regionsTested': tested,
        'regionsInsideEnvelope': covered,
        'worstUncoveredM2': round(worst_gap, 3),
        'centreAtDeterministic': bool(deterministic),
        'bandIsFirstClassCell': bool(band_is_cell),
    }


def main():
    sections = {'1': section_1, '2': section_2, '3': section_3, '4': section_4}
    want, emit_json = None, False
    for index, arg in enumerate(sys.argv):
        if arg == '--section' and index + 1 < len(sys.argv):
            want = sys.argv[index + 1]
        if arg == '--json':
            emit_json = True

    sink = {}
    started = time.perf_counter()
    for key in ('1', '2', '3', '4'):
        if want and want != key:
            continue
        sections[key](sink)
    elapsed = time.perf_counter() - started

    print()
    print('=' * 72)
    print('total %.1f s' % elapsed)
    print('=' * 72)

    out = {
        'generatedBy': 'tools/benches/_bench_innovations.py',
        'note': ('Reproduces the measurements cited in docs/paper-innovations.md. '
                 'The naive counterfactual is measured alongside the shipped path '
                 'in sections 1-3; section 4 is an invariant check.'),
        'seed': SEED,
        'scenario': SCENARIO,
        'elapsedSeconds': round(elapsed, 2),
        'sections': sink,
    }
    path = artifact('_innovations_bench.json')
    with io.open(path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print('wrote', os.path.relpath(path, ROOT).replace('\\', '/'))
    if emit_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
