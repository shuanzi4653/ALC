"""Reconnaissance: can we reach public geographic datasets from this sandbox?

Deliberately read-only and throwaway. Nothing here is part of the application.
"""
import json
import sys
import urllib.request

UA = 'ALC-research/0.1 (low-altitude traffic simulation, contact: project owner)'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OPENER.addheaders = [('User-Agent', UA)]

TARGETS = [
    ('ourairports_airports', 'https://davidmegginson.github.io/ourairports-data/airports.csv'),
    ('nominatim_hongyanhe', 'https://nominatim.openstreetmap.org/search?q='
                            '%E7%BA%A2%E6%B2%BF%E6%B2%B3%E6%A0%B8%E7%94%B5%E7%AB%99&format=json&limit=3'),
    ('overpass_status', 'https://overpass-api.de/api/status'),
]


def probe(name, url, limit=400):
    try:
        with OPENER.open(url, timeout=25) as response:
            body = response.read()
            status = response.status
            ctype = response.headers.get('Content-Type')
    except Exception as exc:  # noqa: BLE001 - reconnaissance wants the raw reason
        print(f'{name}: FAIL {type(exc).__name__}: {exc}')
        return None
    print(f'{name}: HTTP {status} {ctype} {len(body)} bytes')
    print(f'  head: {body[:limit]!r}')
    return body


for name, url in TARGETS:
    probe(name, url)
