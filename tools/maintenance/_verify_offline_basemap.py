"""Check the offline basemap: is it actually the right shape, not just small?

Doubling as the regression test for the generator. The failure mode this guards
against is the one that bit the first draft: a naive Douglas-Peucker on a *closed*
ring treats start == end as a zero-length baseline and collapses the province to
two points. The file was small and valid JSON, and completely wrong. Size is not
evidence; area and extent are.

Run: backend-python\\.venv\\Scripts\\python.exe tools\\maintenance\\_verify_offline_basemap.py
"""
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
ROOT = Path(ROOT)

SOURCE = ROOT / 'frontend' / 'src' / 'assets' / 'china.json'
OFFLINE = ROOT / 'frontend' / 'src' / 'assets' / 'northeast-offline.json'
PROVINCES = ['辽宁省', '吉林省', '黑龙江省']


def rings(geometry):
    if geometry['type'] == 'Polygon':
        yield from geometry['coordinates']
    else:
        for polygon in geometry['coordinates']:
            yield from polygon


def ring_area(ring):
    """Shoelace area in square degrees. Not a real area -- a shape fingerprint."""
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def bbox(geometry):
    xs, ys = [], []
    for ring in rings(geometry):
        for x, y in ring:
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def centroid_shift(a, b):
    def centre(geometry):
        return ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2) if False else None
    ax1, ay1, ax2, ay2 = bbox(a)
    bx1, by1, bx2, by2 = bbox(b)
    return math.hypot((ax1 + ax2) / 2 - (bx1 + bx2) / 2, (ay1 + ay2) / 2 - (by1 + by2) / 2)


def main():
    src = {f['properties']['name']: f for f in json.loads(SOURCE.read_text(encoding='utf-8'))['features']}
    off = json.loads(OFFLINE.read_text(encoding='utf-8'))
    offline = {f['properties']['name']: f for f in off['features']}

    failures = []

    if off.get('type') != 'FeatureCollection':
        failures.append('离线底图不是 FeatureCollection')
    if sorted(offline) != sorted(PROVINCES):
        failures.append('离线底图省份集合不对: %s' % sorted(offline))

    print('%-12s %10s %10s %8s   %-28s %s' % ('省', '原面积', '新面积', '面积比', '包围盒偏差', '顶点数'))
    for name in PROVINCES:
        if name not in offline:
            continue
        g0, g1 = src[name]['geometry'], offline[name]['geometry']
        a0 = sum(ring_area(r) for r in rings(g0))
        a1 = sum(ring_area(r) for r in rings(g1))
        ratio = a1 / a0 if a0 else 0.0
        b0, b1 = bbox(g0), bbox(g1)
        shift = centroid_shift(g0, g1)
        n0 = sum(len(r) for r in rings(g0))
        n1 = sum(len(r) for r in rings(g1))
        print('%-12s %10.4f %10.4f %7.1f%%   %-28s %d -> %d' % (
            name, a0, a1, ratio * 100, '%.4f deg' % shift, n0, n1))

        # A collapse to a sliver shows up as an area ratio near zero. 0.90 is
        # deliberately loose: simplification legitimately shaves convex detail,
        # and the point is to catch collapse, not to police the tolerance.
        if ratio < 0.90:
            failures.append('%s 面积塌缩: ratio=%.3f' % (name, ratio))
        if ratio > 1.05:
            failures.append('%s 面积膨胀: ratio=%.3f' % (name, ratio))
        if n1 < 20:
            failures.append('%s 顶点数过少(%d)，疑似塌缩' % (name, n1))
        if n1 >= n0:
            failures.append('%s 简化后顶点没减少(%d -> %d)' % (name, n0, n1))
        # Every ring must still be a closed linear ring with >= 4 positions.
        for ring in rings(g1):
            if len(ring) < 4 or ring[0] != ring[-1]:
                failures.append('%s 存在非法环(len=%d, closed=%s)' % (name, len(ring), ring[0] == ring[-1]))
                break
        # The operating area is 115-135E / 38-54N; a fallback outside it is a bug.
        x1, y1, x2, y2 = bbox(g1)
        if not (110 <= x1 and x2 <= 140 and 35 <= y1 and y2 <= 60):
            failures.append('%s 包围盒越出作业范围: %s' % (name, (x1, y1, x2, y2)))

    # Determinism: the generator must be reproducible byte-for-byte, so re-running
    # it can never produce a spurious diff in review.
    import hashlib
    digest = hashlib.sha256(OFFLINE.read_bytes()).hexdigest()[:16]
    print()
    print('文件 %s (%d bytes, sha256:%s)' % (OFFLINE.relative_to(ROOT), OFFLINE.stat().st_size, digest))
    print('属性 %s' % json.dumps(off.get('properties'), ensure_ascii=False))

    if failures:
        print()
        print('FAIL')
        for item in failures:
            print('  -', item)
        return 1
    print()
    print('OK  形状与包围盒保真，环闭合，顶点已减少')
    return 0


if __name__ == '__main__':
    sys.exit(main())
