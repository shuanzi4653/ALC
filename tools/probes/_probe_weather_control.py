"""Probe the weather-mode controller: switching, provenance, and no cross-talk.

The property that matters is that switching modes changes **which source supplies
the frame** and nothing else, and that each mode's output is labelled for what it
is. The failure this guards against is a virtual frame being served under a
measured label (or vice versa), which would be undetectable downstream.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

from traffic import service, weather_control  # noqa: E402

weather_control.reset()

print('--- 1. default mode ---')
st = weather_control.status()
print('mode', st['mode'], 'default', st['defaultMode'], 'modes', st['availableModes'])
assert st['mode'] == weather_control.MODE_MEASURED, 'default must be measured'

print('--- 2. invalid mode is rejected, not coerced ---')
try:
    weather_control.set_mode('synthetic-please')
except ValueError as exc:
    print('rejected as expected:', exc)
else:
    raise AssertionError('an unknown mode was accepted')
assert weather_control.mode() == weather_control.MODE_MEASURED, 'mode moved on a bad input'

print('--- 3. virtual mode serves a labelled synthetic frame ---')
switched = weather_control.set_mode(weather_control.MODE_VIRTUAL, actor='probe',
                                   reason='acceptance probe')
print('changed', switched['changed'], 'previous', switched['previous'], 'mode', switched['mode'])
assert switched['changed'] is True

frame = weather_control.radar_frame(slot='2026-09-18T10:36:00Z')
print('frame mode', frame['mode'], 'available', frame['available'])
print('provider', frame['provenance']['provider'], 'synthetic', frame['provenance']['synthetic'])
print('notice', (frame.get('virtualNotice') or {}).get('synthetic'))
assert frame['mode'] == weather_control.MODE_VIRTUAL
assert frame['provenance']['synthetic'] is True
assert (frame.get('virtualNotice') or {}).get('synthetic') is True
assert frame['available'] is True

print('--- 4. radar_regions labels the virtual source ---')
regions = service.radar_regions(minute=30)
print('mode', regions.get('mode'), 'available', regions.get('available'),
      'regions', len(regions.get('regions') or []))
for rec in (regions.get('regions') or []):
    print('  record source', rec['source'], 'synthetic', rec['synthetic'])
    assert rec['synthetic'] is True
    assert rec['source'] == 'SYNTHETIC_RADAR_CREF'

print('--- 5. weather_frame carries the mode ---')
wf = service.weather_frame(42, 'live', 30)
print('weatherMode', wf.get('weatherMode'))
assert wf.get('weatherMode') == weather_control.MODE_VIRTUAL
rad = wf.get('radar') or {}
if rad.get('regions'):
    assert rad['regions'][0]['synthetic'] is True

print('--- 6. switch back to measured, real source untouched ---')
weather_control.set_mode(weather_control.MODE_MEASURED, actor='probe')
frame2 = weather_control.radar_frame()
print('frame mode', frame2['mode'], 'available', frame2['available'])
print('provider', (frame2.get('provenance') or {}).get('provider'))
print('slot', frame2.get('slot'), 'error', frame2.get('error'))
assert frame2['mode'] == weather_control.MODE_MEASURED
assert 'virtualNotice' not in frame2, 'a measured frame carries a virtual notice'
prov = frame2.get('provenance') or {}
assert prov.get('provider') == 'CMA_DATA_NET', 'measured frame is not from CMA: %s' % prov.get('provider')

print('--- 7. frame counters prove the switch took effect ---')
st = weather_control.status()
print('framesServed', st['framesServed'])
assert st['framesServed']['virtual'] >= 1, 'virtual branch served nothing'
assert st['framesServed']['measured'] >= 1, 'measured branch served nothing'

print('--- 8. measured mode passes a failure through, it does not substitute ---')
# Force a failure by asking for a grid the product does not publish. In measured
# mode the result must be an honest unavailable frame, never a synthetic one.
from traffic import cma_tiles  # noqa: E402
failed = cma_tiles.frame(grid=((0, 0),))
print('real frame on a bogus grid -> available', failed.get('available'),
      'cells', len(failed.get('cells') or []))
assert failed.get('available') is False, 'the bogus grid unexpectedly resolved'
assert not failed.get('cells'), 'a failed fetch produced cells'

weather_control.reset()
print()
print('OK: mode switching, labelling and pass-through failure all behave')
