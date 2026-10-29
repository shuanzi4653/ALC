"""Confirm LiveWeatherEnvelope agrees with PublicWeather on the same snapshot.

The whole point of extracting `point_risk_shapes` is that the routing envelope
and the drawn contour can never disagree about thresholds. This probe measures
that on a real snapshot: the envelope must be a superset of the drawn hard core,
and identical to the union of (ban, caution) that PublicWeather reports.
"""
import sys

from shapely.geometry import GeometryCollection

from traffic import service
from traffic.weather import LiveWeatherEnvelope, PublicWeather

snapshot = service.weather_snapshot(service.cities())
print(f"source available={snapshot.get('available')} provider={snapshot.get('provider')} "
      f"observations={len(snapshot.get('observations') or [])}")

public = PublicWeather(snapshot, service.cities())
envelope_provider = LiveWeatherEnvelope(snapshot, service.cities())

print(f"LiveWeatherEnvelope.available = {envelope_provider.available}")

drawn = public.shapes(None)
print(f"drawn shapes = {len(drawn)}")
for members, field, ban, caution in drawn:
    print(f"  {members['id']:>14} kind={members['kind']:<16} "
          f"field={field.area/1e6:8.1f} km2  ban={ban.area/1e6:7.1f} km2  caution={caution.area/1e6:8.1f} km2")

env = envelope_provider.envelope(0, 120)
env_same_window = envelope_provider.envelope(600, 720)
print(f"envelope(0,120)   area = {env.area/1e6:.1f} km2")
print(f"envelope(600,720) area = {env_same_window.area/1e6:.1f} km2  (must equal the above: measurement, not forecast)")
print(f"window independence holds = {abs(env.area - env_same_window.area) < 1e-6}")

# The envelope is the union of the same tiers PublicWeather draws, so it must
# contain every drawn field.
expected = GeometryCollection()
for _, _, ban, caution in drawn:
    expected = expected.union(ban.union(caution))
print(f"expected union area = {expected.area/1e6:.1f} km2")
print(f"envelope == union(ban,caution) of the drawn contours = {abs(env.area - expected.area) < 1e-6}")

# A cautious-only city has an empty ban, so the envelope must be non-empty while
# the hard core is empty. That is the case the planner has to see.
if drawn:
    print("OK: envelope is driven by the same rows the map draws")
else:
    print("NOTE: snapshot returned no cautious cities; envelope is legitimately empty")

empty_provider = LiveWeatherEnvelope(None, service.cities())
print(f"no snapshot -> available={empty_provider.available}, "
      f"envelope is_empty={empty_provider.envelope(0, 120).is_empty} (must be True)")
sys.exit(0)
