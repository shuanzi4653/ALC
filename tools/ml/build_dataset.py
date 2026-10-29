# -*- coding: utf-8 -*-
"""0.10.1 数据 ① 取历史 + ② 抽样（不调用任何模型）。

口径三条（都来自实测，不是偏好）：

1. **数据源用 historical-forecast-api，不用 archive-api**。
   2026-10-17 实测：`archive-api`（ERA5 再分析）对沈阳 2026-09 的 `visibility`
   **整列全 None**（字段在、值不在）；`historical-forecast-api` 同时段 240/240 非空。
   而且线上运行时取的就是**预报产品**（open-meteo current），训练侧必须同口径，
   否则训练用再分析、推用预报，是两个分布。

2. **两个季节都要**：暖季（2026-09）+ 上一个冬季（2025-12…2026-02）。
   11 月演示已入冬，只训 9 月就是分布外。

3. **按气象情景分层抽样，不按规则档抽样**。
   按规则档抽会把规则的偏差写进标签分布（实测规则判 BAN 65%、DANGER 0.14%），
   而按情景抽保证每一类天气都有样本。

产出：
    data/training/raw/<CITY>-<YYYY-MM>.json    原始逐小时（缓存，重复运行不再取数）
    data/training/samples-v1.jsonl             抽样后的样本（含情景标签与判据档位，不含模型输出）
    data/training/dataset-v1.json             数据集元信息（条数、情景分布、字段缺失率、sha256）
"""
import hashlib
import io
import json
import random
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data' / 'training' / 'raw'
OUT_DIR = ROOT / 'data' / 'training'

HOST = 'https://historical-forecast-api.open-meteo.com/v1/forecast'
VARS = ('temperature_2m,relative_humidity_2m,precipitation,rain,snowfall,'
        'cloud_cover,pressure_msl,wind_speed_10m,wind_gusts_10m,visibility,weather_code')

CITIES = {
    'SHE': ('沈阳', 41.80, 123.43),
    'CGQ': ('长春', 43.90, 125.32),
    'HRB': ('哈尔滨', 45.75, 126.63),
}

# 两个季节都必须有，且要**凑够稀有情景**。实测第一版（暖季 1 个月 + 冬季 3 个月）
# 里 `lowvis` 只有 19 小时、`rain` 只有 197 小时 —— 稀有情景靠抽样救不回来，只能扩时间窗。
# 这里补了 2025-11（冬季边缘）、2026-03（冷暖交界）、2026-06/07（对流季，补降水）。
MONTHS = {
    '2025-11': 'winter',
    '2025-12': 'winter',
    '2026-01': 'winter',
    '2026-02': 'winter',
    '2026-03': 'winter',
    '2026-06': 'warm',
    '2026-07': 'warm',
    '2026-09': 'warm',
}

PER_SCENARIO = 200


def month_range(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return f'{ym}-01', f'{ym}-{last:02d}'


def fetch(code, lat, lon, ym):
    cache = RAW / f'{code}-{ym}.json'
    if cache.is_file():
        return json.load(io.open(cache, encoding='utf-8'))
    start, end = month_range(ym)
    url = (f'{HOST}?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}'
           f'&hourly={VARS}&timezone=Asia%2FShanghai')
    req = urllib.request.Request(url, headers={'User-Agent': 'ALC-0.10.1-dataset'})
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.loads(r.read().decode('utf-8'))
    cache.parent.mkdir(parents=True, exist_ok=True)
    with io.open(cache, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return payload


def rows_of(code, ym, payload, season):
    h = payload['hourly']
    out = []
    for i, t in enumerate(h['time']):
        out.append({
            'sampleId': f'{code}-{t.replace(":", "")}',
            'city': code,
            'season': season,
            'month': ym,
            'timeLocal': t,
            'hour': int(t[11:13]),
            'temperatureC': h['temperature_2m'][i],
            'rhPct': h['relative_humidity_2m'][i],
            'precipMmh': h['precipitation'][i],
            'rainMmh': h['rain'][i],
            'snowCmh': h['snowfall'][i],
            'cloudPct': h['cloud_cover'][i],
            'pressureHpa': h['pressure_msl'][i],
            'windMps': h['wind_speed_10m'][i],
            'gustMps': h['wind_gusts_10m'][i],
            'visibilityM': h['visibility'][i],
            'weatherCode': h['weather_code'][i],
        })
    return out


def scenario_of(r):
    """情景分类：先匹配者优先。顺序本身是口径 —— 换顺序会改变各情景的构成。"""
    snow = r['snowCmh']
    precip = r['precipMmh']
    vis = r['visibilityM']
    wind = r['windMps']
    gust = r['gustMps']
    if snow is not None and snow > 0:
        return 'snow'
    if precip is not None and precip > 0:
        return 'rain'
    if vis is not None and vis < 5000:
        return 'lowvis'
    if wind and gust and wind >= 3.0 and gust / wind > 2.6:
        return 'gusty'
    if wind is not None and wind >= 8.0:
        return 'windy'
    return 'calm'


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for code, (name, lat, lon) in CITIES.items():
        for ym, season in MONTHS.items():
            payload = fetch(code, lat, lon, ym)
            rs = rows_of(code, ym, payload, season)
            all_rows.extend(rs)
            vis_missing = sum(1 for r in rs if r['visibilityM'] is None)
            print(f'[OK] {code} {name} {ym} ({season}): {len(rs)} 行，能见度缺 {vis_missing}')

    for r in all_rows:
        r['scenario'] = scenario_of(r)

    rnd = random.Random(20261017)
    picked = []
    for sc in ('calm', 'windy', 'gusty', 'rain', 'lowvis', 'snow'):
        pool = [r for r in all_rows if r['scenario'] == sc]
        rnd.shuffle(pool)
        take = pool[:PER_SCENARIO]
        picked.extend(take)
        print(f'[样本] {sc:7s} 可用 {len(pool):5d} 取 {len(take):4d}')

    # 季节配比检查（A4 判据：两季各 ≥30%）
    seasons = Counter(r['season'] for r in picked)
    total = len(picked)
    print('[季节] ' + ' '.join(f'{k}={v}({v/total*100:.0f}%)' for k, v in seasons.items()))

    with io.open(OUT_DIR / 'samples-v1.jsonl', 'w', encoding='utf-8', newline='\n') as f:
        for r in picked:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    fields = ('temperatureC', 'rhPct', 'precipMmh', 'snowCmh', 'cloudPct',
              'pressureHpa', 'windMps', 'gustMps', 'visibilityM')
    missing = {k: sum(1 for r in picked if r[k] is None) for k in fields}
    blob = (OUT_DIR / 'samples-v1.jsonl').read_bytes()
    meta = {
        'version': 'v1',
        'createdAt': '2026-10-17',
        'source': 'historical-forecast-api.open-meteo.com',
        'cities': {k: v[0] for k, v in CITIES.items()},
        'months': MONTHS,
        'rowsAvailable': len(all_rows),
        'samples': total,
        'perScenario': PER_SCENARIO,
        'scenarioCounts': {sc: sum(1 for r in picked if r['scenario'] == sc)
                           for sc in ('calm', 'windy', 'gusty', 'rain', 'lowvis', 'snow')},
        'seasonShares': {k: round(v / total, 4) for k, v in seasons.items()},
        'missing': missing,
        'sha256': hashlib.sha256(blob).hexdigest(),
    }
    with io.open(OUT_DIR / 'dataset-v1.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print('[OK] 样本 %d 条 -> %s' % (total, OUT_DIR / 'samples-v1.jsonl'))
    print('[OK] sha256 %s' % meta['sha256'])
    print('[缺测] ' + ' '.join(f'{k}={v}' for k, v in missing.items()))


if __name__ == '__main__':
    main()
