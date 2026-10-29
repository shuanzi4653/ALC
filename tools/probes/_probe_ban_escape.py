"""Diagnose why a merged region's BAN escapes its FIELD after the band became a chain.

The failing region is WX-1-01+1: a ring cell clumped with one neighbour. The ban
tier for the band is now a MultiPolygon (one core per cluster), and _dissolve_regions
groups members by "whose field intersects this field component". If a *core* belongs
to a component that is not the one whose members were collected, the ban escapes.

Print the decomposition so the fix is driven by the actual geometry rather than a
guess about which tier is at fault.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from shapely.geometry import shape

from traffic.weather import NetworkWeather
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    world = NetworkWeather(42, 'moving')
    for minute in (0, 30, 60):
        print(f'=== minute {minute}')
        for region in world.frame(minute):
            field = shape(region['field'])
            ban = shape(region['ban'])
            if ban.is_empty:
                continue
            outside = ban.difference(field).area
            if outside < 1.0:
                continue
            print(f"  {region['id']:<22} members={region['memberCount']} "
                  f"ban_outside_field={outside:,.0f} m^2")
            print(f"    field type {field.geom_type}  ban type {ban.geom_type}")
            print(f"    field bounds  {tuple(round(v) for v in field.bounds)}")
            print(f"    ban   bounds  {tuple(round(v) for v in ban.bounds)}")
            # Is the escapee ban component disjoint from the field entirely?
            bans = [ban] if ban.geom_type == 'Polygon' else list(ban.geoms)
            for i, part in enumerate(bans):
                gap = part.distance(field)
                print(f'      ban part {i}: area {part.area:,.0f}  distance to field {gap:,.0f} m')
        print()


if __name__ == '__main__':
    main()
