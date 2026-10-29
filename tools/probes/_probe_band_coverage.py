"""Verify the per-cluster band envelope still covers every cluster it should.

The envelope is no longer one hull of all clusters: it is a union of per-cluster
hulls, which deliberately stops bridging the gaps between separated segments.
That is the point -- a band with passable corridors must not have an envelope
that closes them -- but it moves the risk in the other direction, because an
envelope that is too *small* lets a trajectory thread the rain band.

So this checks the two properties that matter, on real windows:

  1. COVERAGE: for every cluster alive in the window, at every tick in the
     window, the cluster's field outline is inside the swept envelope. This is
     the safety property; a failure here is a serious defect, not a tuning knob.
  2. UNBRIDGED: the envelope does not cover the gap between two adjacent
     clusters that are separated in this window, when such a gap exists. This is
     the property the change was made for.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_band_coverage.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402


def main():
    net = weather.NetworkWeather(seed=7, scenario='nominal')
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    cell = net.cells[band_index]

    print('%6s %8s %12s %12s %10s' %
          ('bins', 'live', 'env km2', 'env-cover sum', 'worst gap m'))
    failures = []
    for start_bin in (0, 12, 24, 36, 48, 60, 72, 84):
        end_bin = start_bin + 14
        ticks = list(range(start_bin, end_bin + 1))
        envelope = net._band_hull(band_index, start_bin, end_bin)
        if envelope.is_empty:
            print('%6d  envelope empty' % start_bin)
            continue

        live_outlines = []
        for cluster in cell.get('clusters', ()):
            for tick in ticks:
                outline, _core = weather._band_cluster_outlines(cluster, tick * 5)
                if outline is not None:
                    live_outlines.append(outline)
        if not live_outlines:
            continue

        # COVERAGE: every drawn outline must sit inside the envelope.
        uncovered = 0
        worst_deficit = 0.0
        for outline in live_outlines:
            outside = outline.difference(envelope)
            if not outside.is_empty and outside.area > 0.0:
                uncovered += 1
                worst_deficit = max(worst_deficit, outside.area)
        if uncovered:
            failures.append('bins %d: %d of %d live outlines not fully covered '
                            '(worst %0.f km2)'
                            % (start_bin, uncovered, len(live_outlines),
                               worst_deficit / 1.0e6))

        # UNBRIDGED: how much air does the envelope claim that is NOT near any
        # cluster? A bridged envelope would show a large such area between
        # clusters; the padded, unbridged one should show little.
        cover = cover_sum = None
        live_union = None
        for outline in live_outlines:
            live_union = outline if live_union is None else live_union.union(outline)
        slack = envelope.difference(live_union.buffer(weather.SWEPT_BAND_PAD_M * 3))
        slack_km2 = slack.area / 1.0e6 if not slack.is_empty else 0.0

        print('%6d %8d %12.1f %12s %10.1f'
              % (start_bin, len(live_outlines), envelope.area / 1.0e6,
                 'all covered' if not uncovered else '%d MISSED' % uncovered,
                 slack_km2))

    print()
    if failures:
        print('FAIL -- %d coverage problem(s)' % len(failures))
        for item in failures:
            print('  ! ' + item)
        return 1
    print('ok -- every cluster outline is inside the swept envelope on every window')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
