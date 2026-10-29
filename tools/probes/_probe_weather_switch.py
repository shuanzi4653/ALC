"""End-to-end check for the weather-channel switch, driven through the ASGI app.

Uses TestClient rather than uvicorn + a local socket: this sandbox blocks
loopback TCP and a urllib call would return the *proxy's* 502, not the app's.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend-python'))

from _repo import ROOT  # noqa: E402  (bootstraps sys.path for backend-python)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from traffic import service, weather_control, radar_field  # noqa: E402

lines = []
client = TestClient(main.app)

# 1. The route the button calls must exist exactly where the component points.
routes = sorted({(r.path, tuple(sorted(getattr(r, 'methods', []) or []))) for r in main.app.routes})
mode_routes = [(p, m) for p, m in routes if 'weather/mode' in p]
lines.append('mode routes: %s' % (mode_routes,))

# 2. Start from the documented default.
weather_control.reset()
r = client.get('/traffic/weather/mode')
lines.append('GET mode -> %s %s' % (r.status_code, {k: r.json()[k] for k in ('mode', 'seed', 'defaultMode')}))
assert r.status_code == 200 and r.json()['mode'] == 'measured'

# 3. Switch to virtual through the same path the button uses.
r = client.post('/traffic/weather/mode', json={'mode': 'virtual', 'actor': 'probe', 'reason': 'button check'})
body = r.json()
lines.append('POST virtual -> %s changed=%s mode=%s' % (r.status_code, body.get('changed'), body.get('mode')))
assert r.status_code == 200 and body['mode'] == 'virtual'

# 4. The frame must now be synthetic AND say so.
frame = service.radar_regions(0)
lines.append('radar mode=%s regions=%s synthetic=%s source=%s' % (
    frame.get('mode'), len(frame.get('regions') or []),
    (frame.get('regions') or [{}])[0].get('synthetic'),
    (frame.get('regions') or [{}])[0].get('source')))
assert frame.get('mode') == 'virtual', 'radar payload must carry the mode'
regions = frame.get('regions') or []
if regions:
    assert regions[0].get('synthetic') is True, 'virtual echoes must be labelled synthetic'
    assert regions[0].get('source') == 'SYNTHETIC_RADAR_CREF', regions[0].get('source')

# 5. The geometry must actually differ from measured, or the switch is cosmetic.
#    Note the layer split: the frame returned by `radar_frame()` is shaped like
#    `cma_tiles.frame()` and carries no band geometry -- bands/components/echoCells
#    only exist after `radar_field.derive()`. Asserting on the raw frame is the
#    mistake this comment exists to prevent.
weather_control.set_mode('virtual', seed=42)
raw = weather_control.radar_frame(slot='2026-09-18T07:18:00Z')
derived = radar_field.derive(raw)
lines.append('virtual derive available=%s echoFraction=%.4f components=%s bands=%s' % (
    derived.get('available'), derived.get('echoFraction') or 0.0,
    derived.get('components'), sorted((derived.get('bands') or {}).keys())))
assert derived.get('available') is True
assert (derived.get('echoFraction') or 0) > 0, 'virtual frame must carry real echoes'
assert derived.get('components'), 'virtual frame must derive at least one component'

# `derive()` stamps its OWN provenance as the national network regardless of the
# input -- which is exactly why the labelling happens upstream in
# `weather_control.radar_frame()`. Recorded here so the next reader does not
# "simplify" the synthetic tags away believing derive() covers them.
lines.append('derive provenance provider=%s (hardcoded; labels come from radar_frame)' % (
    (derived.get('provenance') or {}).get('provider'),))
assert (derived.get('provenance') or {}).get('provider') == 'CMA_DATA_NET'

measured_ok = False
try:
    weather_control.set_mode('measured')
    measured = service.radar_regions(0)
    measured_ok = True
    lines.append('measured regions=%s source=%s' % (
        len(measured.get('regions') or []),
        (measured.get('regions') or [{}])[0].get('source')))
except Exception as exc:
    lines.append('measured frame unavailable as expected-or-not: %s' % exc)
assert measured_ok, 'measured mode must remain reachable after a virtual round-trip'

# 6. Invalid mode must be rejected, not silently coerced.
r = client.post('/traffic/weather/mode', json={'mode': 'REAL'})
lines.append('POST invalid -> %s' % r.status_code)
assert r.status_code == 422, 'unknown mode must 422'

# 7. Determinism: the same slot must reproduce the same raster, or the "replayable
#    demo" promise is empty.
weather_control.set_mode('virtual', seed=42)
a = weather_control.radar_frame(slot='2026-09-18T07:18:00Z')
b = weather_control.radar_frame(slot='2026-09-18T07:18:00Z')
same = a.get('stats') == b.get('stats') and a.get('cells') == b.get('cells')
lines.append('deterministic=%s stats=%s' % (same, a.get('stats')))
assert same, 'identical slot+seed must reproduce the same frame'
# And a different slot must actually evolve, or it is a still image.
c = weather_control.radar_frame(slot='2026-09-18T07:30:00Z')
lines.append('evolves across slots=%s' % (a.get('stats') != c.get('stats')))
assert a.get('stats') != c.get('stats'), 'frames must evolve over time'

weather_control.reset()
lines.append('final mode=%s' % weather_control.mode())

with open(os.path.join(ROOT, '.run', '_switch_probe.txt'), 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(lines) + '\n')
print('\n'.join(lines))
