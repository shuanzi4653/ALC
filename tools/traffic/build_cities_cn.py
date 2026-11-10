# -*- coding: utf-8 -*-
"""构建北方 13 省的地级市目录（名称 + 经纬度）。

数据来源（两条，都可核对）
--------------------------
1. **行政区划**：`modood/Administrative-divisions-of-China` 的 `dist/cities.json`
   （由民政部年度区划整理，含 adcode / name / provinceCode）。
2. **坐标**：Wikidata。先用 `wbgetentities&sites=zhwiki&titles=...` 把中文标题换成 QID，
   再用 `prop=coordinates` 批量取 P625（WGS84）。取不到就**留空**，不凭记忆补。

用法
----
    .venv/Scripts/python.exe tools/traffic/build_cities_cn.py            # 联网抓取
    .venv/Scripts/python.exe tools/traffic/build_cities_cn.py --cached    # 只用 .run/city 缓存

输出 `data/traffic/cities-cn.json`。北方 = 东北三省 + 华北五省区市 + 西北五省区（含新疆）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.run' / 'city'
OUT = ROOT / 'data' / 'traffic' / 'cities-cn.json'

CITIES_URL = 'https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/cities.json'
WIKIDATA = 'https://www.wikidata.org/w/api.php'
UA = 'ALC-tianchuang/1.0.1 (city directory build; contact: project maintainer)'

# 全国省级单元：code → (省名, 大区)。**不含台湾（71）与西藏（54）** —— 用户口径：
# 这两地不通航，不纳入航线网络；也不含港澳（81/82，另有空域管理安排）。
SCOPE = {
    '11': ('北京市', 'north'), '12': ('天津市', 'north'), '13': ('河北省', 'north'),
    '14': ('山西省', 'north'), '15': ('内蒙古自治区', 'north'),
    '21': ('辽宁省', 'northeast'), '22': ('吉林省', 'northeast'), '23': ('黑龙江省', 'northeast'),
    '31': ('上海市', 'east'), '32': ('江苏省', 'east'), '33': ('浙江省', 'east'),
    '34': ('安徽省', 'east'), '35': ('福建省', 'east'), '36': ('江西省', 'east'),
    '37': ('山东省', 'east'),
    '41': ('河南省', 'central'), '42': ('湖北省', 'central'), '43': ('湖南省', 'central'),
    '44': ('广东省', 'central'), '45': ('广西壮族自治区', 'central'), '46': ('海南省', 'central'),
    '50': ('重庆市', 'southwest'), '51': ('四川省', 'southwest'), '52': ('贵州省', 'southwest'),
    '53': ('云南省', 'southwest'),
    '61': ('陕西省', 'northwest'), '62': ('甘肃省', 'northwest'), '63': ('青海省', 'northwest'),
    '64': ('宁夏回族自治区', 'northwest'), '65': ('新疆维吾尔自治区', 'northwest'),
}
EXCLUDED = {'54': '西藏自治区', '71': '台湾省', '81': '香港特别行政区', '82': '澳门特别行政区'}


def curl(url: str, cache: Path, use_cache: bool, tries: int = 5) -> bytes:
    if use_cache and cache.exists() and cache.stat().st_size > 0:
        return cache.read_bytes()
    cache.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(tries):
        proc = subprocess.run(
            ['curl', '-sS', '-m', '40', '--noproxy', '*', '--retry', '3', '--retry-all-errors',
             '-A', UA, '-o', str(cache), '-w', '%{http_code}', url],
            capture_output=True, text=True)
        code = (proc.stdout or '').strip()
        if code == '200' and cache.exists() and cache.stat().st_size > 0:
            return cache.read_bytes()
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f'抓取失败 {url}：{proc.stderr.strip()[:120]}')


def api(params: Dict[str, str], cache: Path, use_cache: bool) -> Dict[str, Any]:
    query = '&'.join(f'{key}={quote(str(value), safe="|")}' for key, value in params.items())
    return json.loads(curl(f'{WIKIDATA}?{query}', cache, use_cache))


def load_city_rows(use_cache: bool) -> List[Dict[str, Any]]:
    rows = json.loads(curl(CITIES_URL, CACHE / 'cities.json', use_cache))
    out: List[Dict[str, Any]] = []
    for row in rows:
        code = row.get('provinceCode')
        if code not in SCOPE:
            continue
        name = row['name']
        province, region = SCOPE[code]
        if name in ('市辖区', '县'):   # 直辖市：地级层只有"市辖区/县"，用市名本身
            name = province
        elif '直辖县级' in name:       # 兵团/省直辖县级单位：不是地级市，跳过
            continue
        out.append({'name': name, 'province': province, 'region': region,
                    'adcode': row['code']})
    return out


def resolve_qids(names: List[str], use_cache: bool, batch: int = 40) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for index in range(0, len(names), batch):
        chunk = names[index:index + batch]
        data = api({'action': 'wbgetentities', 'sites': 'zhwiki', 'titles': '|'.join(chunk),
                    'props': 'sitelinks', 'sitefilter': 'zhwiki', 'format': 'json'},
                   CACHE / f'ent-{index//batch:02d}.json', use_cache)
        for qid, entity in (data.get('entities') or {}).items():
            if qid == '-1' or not isinstance(entity, dict):
                continue
            title = ((entity.get('sitelinks') or {}).get('zhwiki') or {}).get('title')
            if title:
                mapping[title] = qid
        print(f'  实体 {index + len(chunk)}/{len(names)} → 累计 {len(mapping)}', flush=True)
    return mapping


def resolve_coords(qids: List[str], use_cache: bool, batch: int = 45) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for index in range(0, len(qids), batch):
        chunk = qids[index:index + batch]
        data = api({'action': 'query', 'prop': 'coordinates', 'colimit': 'max',
                    'titles': '|'.join(chunk), 'format': 'json'},
                   CACHE / f'coord-{index//batch:02d}.json', use_cache)
        for page in ((data.get('query') or {}).get('pages') or {}).values():
            coords = page.get('coordinates') or []
            if not coords:
                continue
            best = coords[0]
            out[page.get('title')] = {'lon': round(float(best['lon']), 4),
                                      'lat': round(float(best['lat']), 4)}
        print(f'  坐标 {index + len(chunk)}/{len(qids)} → 累计 {len(out)}', flush=True)
    return out


def _province_shapes() -> Dict[str, Any]:
    from shapely.geometry import shape
    asset = ROOT / 'frontend' / 'src' / 'assets' / 'china.json'
    payload = json.loads(asset.read_text(encoding='utf-8'))
    out: Dict[str, Any] = {}
    for feature in payload.get('features') or []:
        name = (feature.get('properties') or {}).get('name')
        if name:
            out[name] = shape(feature['geometry'])
    return out


def repair(rows: List[Dict[str, Any]], use_cache: bool) -> List[Dict[str, Any]]:
    """坐标必须落在本省境内 —— 否则说明标题映射串了（如 zhwiki「白山市」链到别处）。

    处理：拿城市名去 `wbsearchentities` 取前 5 个候选 → 批量取坐标 → 选第一个落在本省的。
    修不了就标 `SUSPECT` / `MISSING`，交给上层如实显示，不猜。
    """
    from shapely.geometry import Point

    shapes = _province_shapes()
    suspects = []
    for row in rows:
        geometry = shapes.get(row['province'])
        if row['lon'] is None or geometry is None:
            if row['lon'] is None:
                suspects.append(row)
            continue
        if row['name'] in OFFSHORE:
            continue
        if not geometry.contains(Point(row['lon'], row['lat'])):
            suspects.append(row)
    if not suspects:
        return rows
    print(f'需要修正 {len(suspects)} 个：' + ', '.join(row["name"] for row in suspects), flush=True)

    for row in suspects:
        geometry = shapes.get(row['province'])
        candidates: List[str] = []
        queries = [row['name'], *ALIAS.get(row['name'], ()),
                   row['name'].rstrip('市') + ' ' + row['province'].rstrip('省市区')]
        for query in dict.fromkeys(queries):
            data = api({'action': 'wbsearchentities', 'search': query, 'language': 'zh',
                        'format': 'json', 'limit': '5', 'type': 'item'},
                       CACHE / f'search-{quote(query, safe="")}.json', use_cache)
            for hit in data.get('search') or []:
                if hit.get('id') and hit['id'] not in candidates:
                    candidates.append(hit['id'])
        if not candidates:
            row['coordSource'] = 'MISSING'
            continue
        points = resolve_coords(candidates[:6], use_cache)
        picked = None
        for qid in candidates[:6]:
            point = points.get(qid)
            if point and geometry is not None and geometry.contains(Point(point['lon'], point['lat'])):
                picked = (qid, point)
                break
        if picked is None:
            row['coordSource'] = 'SUSPECT'
            continue
        row.update({'lon': picked[1]['lon'], 'lat': picked[1]['lat'],
                    'qid': picked[0], 'coordSource': 'WIKIDATA_SEARCH'})
        print(f'  修正 {row["name"]} → {picked[1]["lon"]},{picked[1]["lat"]} ({picked[0]})', flush=True)
    return rows


# 盟 / 自治州 的地级实体本身没有 P625 时，取**驻地**（盟府/州府所在县市）——
# 驻地名是区划常识，坐标仍来自 Wikidata，不手填数字。
SEAT = {'兴安盟': '乌兰浩特市', '阿拉善盟': '阿拉善左旗', '海北藏族自治州': '海晏县',
        '凉山彝族自治州': '西昌市', '黔南布依族苗族自治州': '都匀市'}

# 这些名字直接搜不到实体（同名山体/条目歧义），用更短的关键词再试一次。
ALIAS = {'马鞍山市': ('马鞍山',)}

# 三沙市在南海，省界多边形里本来就没有那些岛礁 —— 不按"越界"处理。
OFFSHORE = {'三沙市'}


def seat_fallback(rows: List[Dict[str, Any]], use_cache: bool) -> List[Dict[str, Any]]:
    from shapely.geometry import Point

    shapes = _province_shapes()
    for row in rows:
        if row['lon'] is not None:
            continue
        seat = SEAT.get(row['name'])
        if not seat:
            continue
        data = api({'action': 'wbsearchentities', 'search': seat, 'language': 'zh',
                    'format': 'json', 'limit': '3', 'type': 'item'},
                   CACHE / f'search-{quote(seat, safe="")}.json', use_cache)
        ids = [hit['id'] for hit in (data.get('search') or []) if hit.get('id')][:3]
        points = resolve_coords(ids, use_cache) if ids else {}
        geometry = shapes.get(row['province'])
        for qid in ids:
            point = points.get(qid)
            if point and geometry is not None and geometry.contains(Point(point['lon'], point['lat'])):
                row.update({'lon': point['lon'], 'lat': point['lat'], 'qid': qid,
                            'nodeName': seat, 'coordSource': 'WIKIDATA_SEAT'})
                print(f'  驻地补点 {row["name"]} → {seat} {point["lon"]},{point["lat"]}', flush=True)
                break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--cached', action='store_true', help='只用 .run/city 缓存，不联网')
    args = parser.parse_args()

    rows = load_city_rows(args.cached)
    names = [row['name'] for row in rows]
    unique = list(dict.fromkeys(names))
    print(f'全国地级单元 {len(rows)} 条，去重标题 {len(unique)} 个', flush=True)

    qids = resolve_qids(unique, args.cached)
    coords = resolve_coords(list(dict.fromkeys(qids.values())), args.cached)

    cities: List[Dict[str, Any]] = []
    missing: List[str] = []
    for row in rows:
        qid = qids.get(row['name'])
        point = coords.get(qid or '')
        if point is None:
            missing.append(row['name'])
            cities.append({**row, 'lon': None, 'lat': None, 'coordSource': 'MISSING'})
        else:
            cities.append({**row, 'lon': point['lon'], 'lat': point['lat'],
                           'coordSource': 'WIKIDATA', 'qid': qid})

    cities = repair(cities, args.cached)
    cities = seat_fallback(cities, args.cached)
    missing = [row['name'] for row in cities if row['lon'] is None]
    suspect = [row['name'] for row in cities if row.get('coordSource') == 'SUSPECT']

    payload = {
        'source': '行政区划 modood/Administrative-divisions-of-China（民政部年度区划整理）；坐标 Wikidata P625（WGS84）',
        'scope': '全国 30 个省级单元（不含台湾、西藏、港澳）',
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'count': len(cities),
        'resolved': len(cities) - len(missing),
        'missing': missing,
        'suspect': suspect,
        'provinces': {code: {'name': name, 'region': region} for code, (name, region) in SCOPE.items()},
        'excluded': EXCLUDED,
        'cities': cities,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'写入 {OUT}：{len(cities)} 城，坐标齐全 {len(cities) - len(missing)}，缺 {len(missing)}，越界存疑 {len(suspect)}')
    if missing:
        print('缺坐标：', ', '.join(missing[:20]))
    if suspect:
        print('越界存疑：', ', '.join(suspect[:20]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
