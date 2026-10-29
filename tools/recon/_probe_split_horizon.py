"""Confirm the split never fires because every candidate birth lands past minute 480."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import random
from pathlib import Path


from traffic import weather as W  # noqa: E402

print('CELL_PREEXISTING_BIRTH_RANGE =', W.CELL_PREEXISTING_BIRTH_RANGE)
print('CELL_LATE_BIRTH_MINUTES      =', W.CELL_LATE_BIRTH_MINUTES)
print('CELL_LIFE_MINUTES            =', W.CELL_LIFE_MINUTES)
print('CELL_DAUGHTER_BIRTH_FRACTION =', W.CELL_DAUGHTER_BIRTH_FRACTION)
print()
print('分裂生物的出生 = 母体出生 + 母体寿命 x [0.30, 0.55]')
print('母体寿命最大 %.0f min，因此最晚出生 = 母体出生 + %.1f min'
      % (W.CELL_LIFE_MINUTES[1], W.CELL_LIFE_MINUTES[1] * 0.55))
print('若母体出生超过 %.1f min，则必然 birth >= 480 -> return None'
      % (480 - W.CELL_LIFE_MINUTES[1] * 0.55))
print()

w = W.NetworkWeather(42, 'moving')
print('seed 42 的母体出生时刻（RING 单体）：')
for cell in w.cells:
    if cell['shape'] != 'RING':
        continue
    latest = cell['birth'] + cell['lifeMinutes'] * W.CELL_DAUGHTER_BIRTH_FRACTION[1]
    earliest = cell['birth'] + cell['lifeMinutes'] * W.CELL_DAUGHTER_BIRTH_FRACTION[0]
    flag = 'OK ' if earliest < 480 else 'X  '
    print(f"  {flag}{cell['id']:<12} birth={cell['birth']:>7.1f} life={cell['lifeMinutes']:>5.1f} "
          f"-> 生物出生区间 [{earliest:>6.1f}, {latest:>6.1f}] min")

print()
print('=' * 78)
print('结论验证：把 480 换成更大视界，分裂能不能生出来？')
print('=' * 78)
rng = random.Random(42)
# Replicate the constructor with the horizon guard relaxed.
cities = W.cities()
conns = W.connections()
rng.sample(conns, 8)
born = 0
candidates = 0
for index, city in enumerate(rng.sample(cities, 20)):
    rng.uniform(5000, 11000)
    life = rng.uniform(*W.CELL_LIFE_MINUTES)
    if rng.random() < W.CELL_PREEXISTING_SHARE:
        birth = rng.uniform(*W.CELL_PREEXISTING_BIRTH_RANGE)
    else:
        birth = rng.uniform(*W.CELL_LATE_BIRTH_MINUTES)
    rng.uniform(-5.5, 5.5)
    rng.uniform(-5.5, 5.5)
    rng.randrange(1 << 30)
    rng.choice(['RAIN', 'STORM', 'WIND'])
    roll = rng.random()
    if roll < W.CELL_SPLIT_SHARE:
        candidates += 1
        d_birth = birth + life * rng.uniform(*W.CELL_DAUGHTER_BIRTH_FRACTION)
        would = '会生出' if d_birth < 480 else '被 480 卡掉'
        print(f'  候选 {candidates}: 母体 birth={birth:>7.1f} 生物出生={d_birth:>6.1f}  {would}')
        if d_birth < 480:
            born += 1
print(f'候选 {candidates} 个，其中能通过 480 视界判定的 {born} 个')
