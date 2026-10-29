import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

from traffic import weather_sim  # noqa: E402

slot = '2026-09-18T10:36:00Z'
slot_index = weather_sim._slot_index(slot)
print('slot_index =', slot_index)
print('LIFE_SLOTS =', weather_sim.LIFE_SLOTS)

alive = 0
for i in range(weather_sim.CELL_COUNT):
    birth = int(weather_sim._hash_unit(42, i, 'birth') * weather_sim.LIFE_SLOTS)
    age = slot_index - birth
    st = weather_sim._cell_state(42, i, slot_index)
    print(i, 'birth', birth, 'age', age, 'state', 'None' if st is None else
          'x=%.1f y=%.1f peak=%.1f r=%.1f' % (st['field_x'], st['field_y'], st['peak'], st['radius']))
    if st:
        alive += 1
print('alive', alive, 'of', weather_sim.CELL_COUNT)
