"""Why does the split model never fire? Replay __init__'s rng consumption order."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import random
from pathlib import Path


from traffic import weather as W  # noqa: E402

print('CELL_SPLIT_SHARE            =', W.CELL_SPLIT_SHARE)
print('CELL_DAUGHTER_BIRTH_FRACTION=', W.CELL_DAUGHTER_BIRTH_FRACTION)
print('CELL_PREEXISTING_SHARE      =', W.CELL_PREEXISTING_SHARE)
print('CELL_LATE_BIRTH_MINUTES     =', W.CELL_LATE_BIRTH_MINUTES)
print()

for seed in (1, 7, 13, 42, 99, 2026):
    rng = random.Random(seed)
    cities = W.cities()
    conns = W.connections()
    rng.sample(conns, 8)
    vals = []
    for index, city in enumerate(rng.sample(cities, 20)):
        rng.uniform(5000, 11000)                      # radius
        rng.uniform(*W.CELL_LIFE_MINUTES)             # life
        rng.random()                                  # preexisting?
        rng.uniform(0, 0)                             # (either birth branch consumes one uniform)
        rng.uniform(-5.5, 5.5)                        # wind x
        rng.uniform(-5.5, 5.5)                        # wind y
        rng.randrange(1 << 30)                        # shape seed
        rng.choice(['RAIN', 'STORM', 'WIND'])         # kind
        vals.append(rng.random())                     # the split roll
    fires = [v for v in vals if v < W.CELL_SPLIT_SHARE]
    print(f'seed {seed:>5}: 分裂判定值 min={min(vals):.4f} max={max(vals):.4f} '
          f' 触发 {len(fires)}/{len(vals)}  阈值={W.CELL_SPLIT_SHARE}')

print()
print('观察：若 max 远低于阈值而触发数仍为 0，说明判定值整体偏大；')
print('若触发数 >0 但 NetworkWeather 里为 0，说明 rng 消耗顺序与真实实现不一致。')
print()

# Ground truth: instrument the real constructor.
real_random = random.Random


class Spy(real_random):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rolls = []

    def random(self):
        v = super().random()
        self.rolls.append(v)
        return v


spies = []


def factory(*a, **k):
    s = Spy(*a, **k)
    spies.append(s)
    return s


random.Random = factory
try:
    for seed in (1, 7, 13, 42, 99, 2026):
        spies.clear()
        w = W.NetworkWeather(seed, 'moving')
        kids = [c for c in w.cells if c.get('parent')]
        rolls = spies[0].rolls if spies else []
        below = [r for r in rolls if r < W.CELL_SPLIT_SHARE]
        print(f'真实构造 seed {seed:>5}: random() 调用 {len(rolls)} 次，'
              f'其中 <{W.CELL_SPLIT_SHARE} 的 {len(below)} 个，'
              f'分裂单体 {len(kids)} 个')
finally:
    random.Random = real_random
