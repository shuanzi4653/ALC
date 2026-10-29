"""A/B: the early rejects in `conflict` must not change a single verdict.

Idea
----
`conflict` was measured at 22.4% of plan time (115,845 calls, 22.4 us each), so it
is the right place to look. Two cheap necessary-condition rejects were added ahead
of the arithmetic. A faster function that answers differently is not an
optimisation, it is a defect -- so this probe compares the new implementation
against a **verbatim copy of the old one** over a large randomised corpus, and
fails if they ever disagree.

The corpus is built to include the cases the rejects could plausibly get wrong:
  * pairs that are far apart in 2-D but overlap in time (the common reject case);
  * pairs that pass very close but whose endpoints are all far apart (the case
    where endpoint distance is a loose bound -- these must still reach the slow
    path and be judged there);
  * pairs that overlap in 2-D and in time, vertically separated by just under and
    just over the threshold;
  * degenerate zero-length segments and single-point paths.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_conflict_early_reject.py
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'backend-python'))

from traffic.spatial import conflict as fast_conflict  # noqa: E402
from traffic.spatial import bbox_2d  # noqa: E402

HORIZONTAL = 250.0
VERTICAL = 60.0


def reference_conflict(a, b, horizontal=HORIZONTAL, vertical=VERTICAL):
    """The pre-2026-10-01 implementation, copied verbatim for comparison."""
    for p, q in zip(a, a[1:]):
        for r, s in zip(b, b[1:]):
            lo, hi = max(p[3], r[3]), min(q[3], s[3])
            if hi < lo:
                continue
            va = [(q[key] - p[key]) / (q[3] - p[3]) for key in range(3)]
            vb = [(s[key] - r[key]) / (s[3] - r[3]) for key in range(3)]
            delta = [p[key] + va[key] * (lo - p[3]) - r[key] - vb[key] * (lo - r[3]) for key in range(3)]
            velocity = [va[key] - vb[key] for key in range(3)]
            left, right = 0.0, hi - lo
            if abs(velocity[2]) < 1e-10:
                if abs(delta[2]) > vertical:
                    continue
            else:
                interval = sorted(((-vertical - delta[2]) / velocity[2], (vertical - delta[2]) / velocity[2]))
                left, right = max(left, interval[0]), min(right, interval[1])
            if left > right:
                continue
            velocity_squared = velocity[0] ** 2 + velocity[1] ** 2
            moment = left if velocity_squared < 1e-10 else max(
                left, min(right, -(delta[0] * velocity[0] + delta[1] * velocity[1]) / velocity_squared)
            )
            if (delta[0] + velocity[0] * moment) ** 2 + (delta[1] + velocity[1] * moment) ** 2 <= horizontal ** 2:
                return True
    return False


def segment(x, y, z, t):
    return [x, y, z, t]


def corpus(rng):
    """Cases the two implementations must agree on, including the hard ones."""
    cases = []

    # 1. Far apart in 2-D, overlapping in time -> the new reject fires.
    for _ in range(400):
        x = rng.uniform(-5000, 5000)
        y = rng.uniform(-5000, 5000)
        a = [segment(x, y, 500, 0), segment(x + 900, y + 120, 520, 12)]
        gap = rng.uniform(400, 3000)
        b = [segment(x + gap, y, 500, 0), segment(x + gap + 900, y + 120, 520, 12)]
        cases.append((a, b))

    # 2. **Endpoint distance is a loose bound**: two long segments passing within
    #    a few metres of each other while all four endpoints are far apart. The
    #    new reject must NOT fire here, and the slow path must still find the
    #    crossing. This is the case that would break a naive bounding-box reject.
    for _ in range(400):
        a = [segment(-2000, 0, 500, 0), segment(2000, 0, 500, 40)]
        offset = rng.uniform(-400, 400)
        # A near-vertical segment crossing the first one near the origin.
        b = [segment(0, -2000 + offset, 500, 0), segment(0, 2000 + offset, 500, 40)]
        cases.append((a, b))

    # 3. Overlapping in 2-D and time, vertical separation swept across the line.
    for offset in (VERTICAL - 1, VERTICAL, VERTICAL + 1, VERTICAL - .05, VERTICAL + .05):
        a = [segment(0, 0, 500, 0), segment(1000, 0, 500, 20)]
        b = [segment(0, -100, 500 + offset, 0), segment(1000, 100, 500 + offset, 20)]
        cases.append((a, b))

    # 4. Random near-field pairs: short segments close together, which is where
    #    most real conflicts and near-misses live.
    for _ in range(1500):
        x, y = rng.uniform(-3000, 3000), rng.uniform(-3000, 3000)
        a = [segment(x, y, rng.uniform(300, 900), 0),
             segment(x + rng.uniform(-600, 600), y + rng.uniform(-600, 600), rng.uniform(300, 900), rng.uniform(1, 20))]
        b = [segment(x + rng.uniform(-800, 800), y + rng.uniform(-800, 800), rng.uniform(300, 900), rng.uniform(0, 5)),
             segment(x + rng.uniform(-800, 800), y + rng.uniform(-800, 800), rng.uniform(300, 900), rng.uniform(10, 30))]
        cases.append((a, b))

    # 5. Degenerate geometry that is still *well-formed in time*: a single-point
    #    path (no segments at all) against a real one.
    #
    #    Deliberately NOT included: a zero-duration segment (t_start == t_end).
    #    The reference implementation divides by `q[3] - p[3]` with no guard and
    #    raises ZeroDivisionError, so it is not a case the two can be compared
    #    on -- and the same is true of the shipped code. Real trajectories come
    #    from `_line`/samplers where `t` strictly increases, so this is a latent
    #    robustness gap rather than a live defect; see ISSUES for the note.
    for _ in range(200):
        a = [segment(0, 0, 500, 0), segment(100, 0, 500, 10)]
        point = [segment(rng.uniform(-500, 500), 0, 500, 5)]
        cases.append((a, point))
        cases.append((point, a))
        cases.append((point, [segment(0, 0, 500, 0), segment(50, 0, 500, 10)]))

    return cases


def main():
    rng = random.Random(20261001)
    cases = corpus(rng)
    mismatches = []
    boxed_mismatches = []
    conflicts = 0
    for index, (a, b) in enumerate(cases):
        slow = reference_conflict(a, b)
        fast = fast_conflict(a, b)
        if slow:
            conflicts += 1
        if slow != fast:
            mismatches.append((index, slow, fast, a, b))
        # 2026-10-03 加了第三道预筛（整对航迹的外接矩形），并且**规划器走的是
        # 预计算足迹那条路**（`box_a`/`box_b` 由调用方算好传进来）。只测默认参数
        # 就等于只测了一条产品不走的支路 —— 上一轮已经在"注入打在了别的地方"上栽过
        # 一次（M58/M61）。所以同一个语料要**两条路都测**：默认、以及把 `bbox_2d`
        # 的结果显式传进去。两条都必须与旧实现逐例一致。
        boxed = fast_conflict(a, b, box_a=bbox_2d(a), box_b=bbox_2d(b))
        if slow != boxed:
            boxed_mismatches.append((index, slow, boxed, a, b))

    print('cases        %d' % len(cases))
    print('conflicts    %d (%.1f%%)' % (conflicts, 100.0 * conflicts / len(cases)))
    print('mismatches   %d  (default path)' % len(mismatches))
    print('mismatches   %d  (precomputed-footprint path -- the one the planner uses)'
          % len(boxed_mismatches))
    for row in (mismatches + boxed_mismatches)[:5]:
        print('  #%d slow=%s fast=%s' % (row[0], row[1], row[2]))
        print('    a=%s' % (row[3],))
        print('    b=%s' % (row[4],))

    # The corpus must actually contain conflicts, otherwise "agrees everywhere"
    # only proves both implementations always say no.
    if conflicts == 0:
        print('FAIL -- corpus produced no conflicts; agreement is vacuous')
        return 1
    if mismatches or boxed_mismatches:
        print('FAIL -- early rejects changed a verdict')
        return 1
    print('CONFLICT EARLY REJECT PASS -- %d cases, %d conflicts, 0 disagreements'
          % (len(cases), conflicts))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
