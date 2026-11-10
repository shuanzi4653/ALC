# -*- coding: utf-8 -*-
"""抓全国机场站点（ICAO + 坐标），并挂到最近的地级市。

数据源：`aviationweather.gov` 的 `stationinfo`（机场/报文中继站点总表，**与当前是否发报无关**）。
按省 bbox 逐省取，避免一次 bbox 被条数上限截断；只保留 `country=CN`。

为什么不用实时 METAR 反推机场
----------------------------
实时报文只包含"此刻在发报的站"，同一套代码两次跑结果不同（网络 504、某站临时不发报都会变），
网络拓扑会因此漂移。机场是相对稳定的物理事实，用站点总表，落成文件后再离线可复现。

    .venv/Scripts/python.exe tools/traffic/build_airports.py

输出 `data/traffic/airports-cn.json`。
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
CITY_FILE = ROOT / 'data' / 'traffic' / 'cities-cn.json'
OUT = ROOT / 'data' / 'traffic' / 'airports-cn.json'
UA = 'ALC-tianchuang/1.0.1 (airport directory; contact: project maintainer)'
URL = 'https://aviationweather.gov/api/data/stationinfo'
MAX_LINK_KM = 60.0     # 机场到市中心多远之内算"这个市的机场"

# 省会（直辖市用自身）。机场挂接时的首选城市，见下面的注释。
CAPITALS = {
    '北京市': '北京市', '天津市': '天津市', '河北省': '石家庄市', '山西省': '太原市',
    '内蒙古自治区': '呼和浩特市', '辽宁省': '沈阳市', '吉林省': '长春市', '黑龙江省': '哈尔滨市',
    '上海市': '上海市', '江苏省': '南京市', '浙江省': '杭州市', '安徽省': '合肥市',
    '福建省': '福州市', '江西省': '南昌市', '山东省': '济南市', '河南省': '郑州市',
    '湖北省': '武汉市', '湖南省': '长沙市', '广东省': '广州市', '广西壮族自治区': '南宁市',
    '海南省': '海口市', '重庆市': '重庆市', '四川省': '成都市', '贵州省': '贵阳市',
    '云南省': '昆明市', '陕西省': '西安市', '甘肃省': '兰州市', '青海省': '西宁市',
    '宁夏回族自治区': '银川市', '新疆维吾尔自治区': '乌鲁木齐市',
}


def haversine(a, b) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def fetch_box(bbox: str, cache: Path) -> List[Dict[str, Any]]:
    for attempt in range(4):
        proc = subprocess.run(
            ['curl', '-sS', '-m', '45', '--noproxy', '*', '--retry', '2', '--retry-all-errors',
             '-A', UA, '-o', str(cache), '-w', '%{http_code}',
             f'{URL}?bbox={bbox}&format=json'],
            capture_output=True, text=True)
        if (proc.stdout or '').strip() == '200' and cache.exists():
            try:
                return json.loads(cache.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                pass
        time.sleep(2 + 2 * attempt)
    return []


def main() -> int:
    from shapely.geometry import shape, Point

    china = json.loads((ROOT / 'frontend' / 'src' / 'assets' / 'china.json').read_text(encoding='utf-8'))
    shapes = {f['properties']['name']: shape(f['geometry']) for f in china['features']
              if (f.get('properties') or {}).get('name')}
    cities = [row for row in json.loads(CITY_FILE.read_text(encoding='utf-8'))['cities']
              if row.get('lon') is not None]

    cache_dir = ROOT / '.run' / 'city'
    cache_dir.mkdir(parents=True, exist_ok=True)
    stations: Dict[str, Dict[str, Any]] = {}
    for name, geometry in shapes.items():
        if name not in {city['province'] for city in cities}:
            continue
        minx, miny, maxx, maxy = geometry.bounds
        rows = fetch_box(f'{miny:.2f},{minx:.2f},{maxy:.2f},{maxx:.2f}',
                         cache_dir / f'airport-{name}.json')
        kept = 0
        for row in rows:
            if row.get('country') != 'CN' or not row.get('icaoId'):
                continue
            if not (row.get('siteType') or ['METAR']) or 'METAR' not in (row.get('siteType') or ['METAR']):
                continue
            if not geometry.contains(Point(row['lon'], row['lat'])):
                continue
            stations[row['icaoId']] = {'icao': row['icaoId'], 'site': row.get('site'),
                                       'lat': row['lat'], 'lon': row['lon'],
                                       'province': name}
            kept += 1
        print(f'  {name}: {kept} 站', flush=True)

    # 挂到最近城市：**省会是例外** —— 机场常以省命名、落在邻市境内（太原武宿在晋中、
    # 西宁曹家堡在海东、兰州中川在白银），按"离谁近算谁的"会把省会判成没有机场。
    # 规则：机场离省会 ≤ 60 km 就记给省会；否则记给最近的地级市。
    by_name = {city['name']: city for city in cities}
    capitals = {province: by_name[name] for province, name in CAPITALS.items() if name in by_name}
    for station in stations.values():
        best = None
        for city in cities:
            distance = haversine((station['lon'], station['lat']), (city['lon'], city['lat']))
            if best is None or distance < best[0]:
                best = (distance, city)
        capital = capitals.get(station['province'])
        if capital is not None:
            capital_distance = haversine((station['lon'], station['lat']),
                                         (capital['lon'], capital['lat']))
            if capital_distance <= MAX_LINK_KM and (best is None or capital_distance <= best[0] + 40.0):
                station.update({'city': capital['name'], 'distanceKm': round(capital_distance, 1),
                                'assignedBy': 'CAPITAL'})
                continue
        if best and best[0] <= MAX_LINK_KM:
            station['city'] = best[1]['name']
            station['distanceKm'] = round(best[0], 1)
            station['assignedBy'] = 'NEAREST'
        else:
            station['city'] = None
            station['distanceKm'] = round(best[0], 1) if best else None
            station['assignedBy'] = 'UNASSIGNED'

    airport_cities = sorted({s['city'] for s in stations.values() if s['city']})
    payload = {
        'source': 'aviationweather.gov stationinfo（机场/报文站总表，按省 bbox 逐省获取，仅 country=CN）',
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'maxLinkKm': MAX_LINK_KM,
        'stations': len(stations),
        'airportCities': airport_cities,
        'stationRows': sorted(stations.values(), key=lambda row: (row['province'], row['icao'])),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'写入 {OUT}：{len(stations)} 站 / {len(airport_cities)} 个机场城市')
    return 0


if __name__ == '__main__':
    sys.exit(main())
