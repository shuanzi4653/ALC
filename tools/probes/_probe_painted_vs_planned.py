"""Read the cached plan and report whether its routes respect the painted echo.

Why: the operator reports aircraft and a corridor line sitting inside a red
"risk area" with no detour. Three different faults look identical on screen --

  1. the plan really does not consume the painted geometry (a routing gap),
  2. the planner consumes a *different* set than the map paints (the classic
     "two sources, one picture" fault of this project), or
  3. the planner avoids it correctly and what is on screen is a stale plan.

This probe separates them before any code is touched. Run it with the venv
interpreter (it imports shapely through the traffic package).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend-python'))

from shapely.geometry import LineString, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from traffic import radar_field, service, weather_control  # noqa: E402

STORE = Path(service.STORE)


def load():
    files = sorted(STORE.glob('*.json'))
    assert files, f'no cached plan under {STORE}'
    path = files[-1]
    with path.open(encoding='utf-8') as handle:
        return path, json.load(handle)


def main():
    path, plan = load()
    print(f'plan   {path.name}  fingerprint={plan.get("fingerprint")} '
          f'(current {service.FINGERPRINT})')
    print(f'seed={plan.get("seed")} scenario={plan.get("scenario")} '
          f'virtual={weather_control.is_virtual()}')
    keys = [k for k in plan if 'radar' in k.lower() or 'weather' in k.lower()]
    print('weather-ish top keys:', keys)
    ra = plan.get('radarAvoidance')
    print('radarAvoidance =', json.dumps(ra, ensure_ascii=False)[:600])

    flights = plan.get('flights') or plan.get('plan', {}).get('flights') or []
    print(f'flights {len(flights)}')
    accepted = [f for f in flights if f.get('points') and f.get('accepted', True)
                and f.get('reason') in (None, '')]
    print(f'accepted-ish {len(accepted)}')
    if flights:
        print('flight keys sample:', sorted(flights[0])[:30])

    # The painted geometry, minute by minute, exactly as the map asks for it.
    stride = 60
    worst = []
    for minute in range(0, 481, stride):
        try:
            payload = service.radar_regions(minute)
        except Exception as exc:  # noqa: BLE001
            print(f'minute {minute}: radar_regions raised {exc!r}')
            continue
        ban = [shape(f['geometry']) for f in payload.get('regions', [])
               if f.get('properties', {}).get('tier') == 'BAN']
        if not ban:
            print(f'minute {minute}: no BAN features '
                  f'(keys {sorted(payload)[:8]})')
            continue
        ban_union = unary_union(ban).buffer(0)
        inside = []
        for flight in accepted:
            line = LineString([(p[0], p[1]) for p in flight['points']])
            if line.intersects(ban_union):
                inside.append(flight['id'])
        print(f'minute {minute}: ban={ban_union.area / 1e6:,.0f} km2  '
              f'pieces={len(ban)}  routes crossing={len(inside)}  '
              f'{inside[:6]}')
        worst.append((len(inside), minute, ban_union.area / 1e6))
    if worst:
        worst.sort(reverse=True)
        print('worst minutes:', worst[:5])


if __name__ == '__main__':
    main()
