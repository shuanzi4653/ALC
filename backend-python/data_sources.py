import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.engine import REGIONS
from weather.geometry import boundary, project
from shapely.geometry import Point

DATA = Path(__file__).resolve().parent / 'data' / 'stations'
CATALOG_URL = 'https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv'

def normalize(row):
    def value(key, position, qc_position, missing, scale=1):
        parts = row.get(key, '').split(',')
        try:
            if parts[qc_position] not in ('1', '5') or parts[position].lstrip('+') == missing:
                return None
            return float(parts[position]) / scale
        except (IndexError, ValueError):
            return None
    return dict(observedAt=row['DATE'] + ('Z' if not row['DATE'].endswith('Z') else ''),
                windSpeedMps=value('WND', 3, 4, '9999', 10),
                windDirectionDeg=value('WND', 0, 1, '999'),
                temperatureC=value('TMP', 0, 1, '9999', 10),
                visibilityM=value('VIS', 0, 1, '999999'),
                precipitationAccumulationMm=value('AA1', 1, 3, '9999', 10),
                precipitationPeriodHours=value('AA1', 0, 3, '99'),
                thunderProbability=None, rawQuality={k: row.get(k) for k in ('WND', 'TMP', 'VIS', 'AA1')})

def catalog_rows(raw):
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        try:
            coord = [float(row['LON']), float(row['LAT'])]
        except ValueError:
            continue
        if row['CTRY'] != 'CH':
            continue
        for rid, region in REGIONS.items():
            if boundary(region['name']).covers(Point(project(coord))):
                rows.append(dict(stationId=row['USAF'] + row['WBAN'], name=row['STATION NAME'],
                                 coord=coord, regionId=rid, begin=row['BEGIN'], end=row['END'],
                                 source='NOAA_ISD_CATALOG', sourceUrl=CATALOG_URL))
    return rows

def observations():
    regions = []
    for rid, region in REGIONS.items():
        path = DATA / f'{rid}.json'
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            regions.append({**saved, 'regionId': rid, 'regionName': region['name'],
                            'status': 'HISTORICAL', 'forecastStatus': 'NO_DATA'})
        except FileNotFoundError:
            regions.append(dict(regionId=rid, regionName=region['name'], status='NO_DATA',
                                forecastStatus='NO_DATA', samples=[], stations=[]))
        except (ValueError, OSError):
            regions.append(dict(regionId=rid, regionName=region['name'], status='ERROR',
                                forecastStatus='NO_DATA', samples=[], stations=[]))
    return dict(source='HISTORICAL_STATION', regions=regions,
                note='历史站点观测，不是实时数据或区域雷暴预报；缺测保持为空。')

def download():
    import httpx
    DATA.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=45, trust_env=False, follow_redirects=True) as client:
        response = client.get(CATALOG_URL); response.raise_for_status()
        stations = catalog_rows(response.text)
        (DATA / 'catalog.json').write_text(json.dumps(dict(sourceUrl=CATALOG_URL,
            retrievedAt=datetime.now(timezone.utc).isoformat(), sha256=hashlib.sha256(response.content).hexdigest(),
            stations=stations), ensure_ascii=False, indent=2), encoding='utf-8')
        for rid, region in REGIONS.items():
            candidates = [s for s in stations if s['end'] >= '20250101' and s['begin'] <= '20251231']
            candidates = sorted((s for s in candidates if s['regionId'] == rid),
                                key=lambda s: Point(project(s['coord'])).distance(Point(project(region['center']))))
            for station in candidates[:5]:
                url = f"https://www.ncei.noaa.gov/data/global-hourly/access/2025/{station['stationId']}.csv"
                try:
                    response = client.get(url); response.raise_for_status()
                    rows = list(csv.DictReader(io.StringIO(response.text)))
                    samples = [normalize(r) for r in rows if r['DATE'].startswith('2025-07-01')]
                    if not samples:
                        continue
                    result = dict(sourceUrl=url, retrievedAt=datetime.now(timezone.utc).isoformat(),
                                  rawSha256=hashlib.sha256(response.content).hexdigest(), stations=[station], samples=samples)
                    (DATA / f'{rid}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(rid, station['stationId'], len(samples), flush=True)
                    break
                except httpx.HTTPError as exc:
                    print(rid, station['stationId'], type(exc).__name__, flush=True)

if __name__ == '__main__':
    download()
