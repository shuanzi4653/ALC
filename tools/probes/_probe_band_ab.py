"""A/B: what the mis-projected rain band cost the plan.

The band's outline was authored in raw northing/easting and never projected, so it
sat ~4300 km north of the network. Its own envelope therefore contributed no
lateral avoidance anywhere near the operation, while the *display* clipped to an
empty polygon. This probe measures the plan with the band's envelope absent and
with it present, on the same seed and scenario, so the size of the defect is a
measurement rather than a claim.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, ARTIFACTS  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ARTIFACTS = Path(ARTIFACTS)
import json
import time

from shapely.geometry import GeometryCollection


from traffic import service  # noqa: E402
from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


ORIGINAL_SWEPT_BAND = NetworkWeather._swept_band


def summarise(result):
    flights = result.get('flights') or []
    reasons = {}
    for flight in flights:
        key = flight.get('reason')
        reasons[key] = reasons.get(key, 0) + 1
    stats = result.get('stats') or {}
    return {
        'flights': len(flights),
        'accepted': stats.get('accepted'),
        'closed': stats.get('closed'),
        'detours': stats.get('detours'),
        'resolved': stats.get('resolved'),
        'reasons': dict(sorted(reasons.items(), key=lambda item: -item[1])),
        'flightsRequiringApproval': (stats.get('staticAirspace') or {}).get('flightsRequiringApproval'),
    }


def band_envelope_absent(self, cell, start_bin, end_bin):
    # Reproduces the defect exactly: the band's envelope was present but displaced,
    # so it avoided nothing where the band actually is.
    return GeometryCollection()


rows = {}
started = time.time()
rows['band_envelope_active'] = summarise(service.simulate(42, 'moving'))
NetworkWeather._swept_band = band_envelope_absent
rows['band_envelope_absent'] = summarise(service.simulate(42, 'moving'))
NetworkWeather._swept_band = ORIGINAL_SWEPT_BAND
rows['seconds'] = round(time.time() - started, 2)

before = rows['band_envelope_absent']
after = rows['band_envelope_active']
rows['delta'] = {
    'weatherBlocked': after['reasons'].get('WEATHER_BLOCKED', 0) - before['reasons'].get('WEATHER_BLOCKED', 0),
    'closed': (after['closed'] or 0) - (before['closed'] or 0),
    'accepted': (after['accepted'] or 0) - (before['accepted'] or 0),
    'detours': (after['detours'] or 0) - (before['detours'] or 0),
}

print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
out = Path(ARTIFACTS) / '.run' / 'band_ab.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
