# -*- coding: utf-8 -*-
"""0.11.1 数据 ① 拉取三站 METAR 实测观测（**真实观测**，非模式估算）。

为什么换源（这是 0.11.1 的核心决定，推翻前先读完）：
    0.10.1 的标签来自 `config/labels-v1.json` 判据，`tool/train_model.py` 自己写着
    「macroF1 衡量的是复现判据的能力，不是预测天气的能力」。手册 §8.1 把这条判为
    45 分的全部来源：**模型学的是自己的 if-else**。
    0.11.1 把标签换成 3 站 METAR 实测（ZYTX 沈阳 / ZYCC 长春 / ZYHB 哈尔滨），
    预测目标换成"未来 1–3 h 是否出现低能见度 / 强阵风"。

数据源：Iowa State University ASOS archive（`mesonet.agron.iastate.edu/cgi-bin/request/asos.py`）
    - `report_type=3` = 逐小时 routine METAR（FM-15），与低空决策的时效匹配；
    - `vsby` 单位是**法定英里**（6.21 SM ≈ 10 km），必须换算成米；
    - `gust`/`sknt` 单位是**节**，必须换算成 m/s；
    - `tmpf`/`dwpf` 是华氏度；
    - `skyl1` 是云底高（英尺），`M` 表示缺测。

产出：
    data/training/metar/raw/<ICAO>-<YYYY>.csv    原始 CSV（缓存，重复运行不再取数）
    data/training/metar/series.csv               清洗后的逐小时序列（全字段 SI 单位）
    data/training/metar/dataset.json             元信息（条数、缺测率、时间范围、sha256）
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data' / 'training' / 'metar'
RAW = OUT / 'raw'

HOST = 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py'
# `mslp` 在 `report_type=3` 下**整列不返回**（实测 0/8736）；改取 `alti`（修正海压，英寸汞柱）。
# `gust` 只在"确有阵风"时才有值（实测 205/8736）—— 缺测的语义是"没有阵风"，
# 不是"没观测到"，所以用持续风回填，并把回填事实单列一列 `gustSource`。
FIELDS = ('vsby', 'gust', 'sknt', 'drct', 'tmpf', 'dwpf', 'skyl1', 'alti', 'skyc1')

# 站点坐标与海拔：机场基准点（用于走廊插值）。海拔单位米。
STATIONS = {
    'ZYTX': {'name': '沈阳桃仙', 'lat': 41.6398, 'lon': 123.4833, 'elev': 60.0},
    'ZYCC': {'name': '长春龙嘉', 'lat': 43.9962, 'lon': 125.6853, 'elev': 215.0},
    'ZYHB': {'name': '哈尔滨太平', 'lat': 45.6234, 'lon': 126.2500, 'elev': 139.0},
}

YEARS = range(2019, 2026)      # 2019–2025；测试集按时间切在 2025（见 train_nowcast.py）

SM_TO_M = 1609.344
KT_TO_MS = 0.514444
FT_TO_M = 0.3048


def _f(v):
    """ASOS 的缺测是字符串 `M`，还有 `T`（trace）与空串。只认真正的数字。"""
    if v is None:
        return None
    s = str(v).strip()
    if s in ('', 'M', 'T', 'None'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch(station: str, year: int) -> str:
    path = RAW / f'{station}-{year}.csv'
    if path.is_file() and path.stat().st_size > 200:
        return path.read_text(encoding='utf-8', errors='replace')
    query = '&'.join(f'data={f}' for f in FIELDS)
    url = (f'{HOST}?station={station}&{query}'
           f'&year1={year}&month1=1&day1=1&year2={year}&month2=12&day2=31'
           f'&tz=UTC&format=onlycomma&latlon=no&missing=M&trace=T&direct=no&report_type=3')
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ALC-tianchuang/0.11.1 (research)'})
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode('utf-8', errors='replace')
            if 'station,valid' not in body.splitlines()[0]:
                raise ValueError(f'unexpected header: {body[:120]!r}')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding='utf-8')
            return body
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:  # noqa: PERF203
            last = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f'{station} {year} 拉取失败: {last}')


def parse(body: str, station: str):
    rows = []
    for row in csv.DictReader(io.StringIO(body)):
        valid = (row.get('valid') or '').strip()
        if not valid:
            continue
        try:
            ts = datetime.strptime(valid, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        vsby = _f(row.get('vsby'))
        gust = _f(row.get('gust'))
        sknt = _f(row.get('sknt'))
        tmpf = _f(row.get('tmpf'))
        dwpf = _f(row.get('dwpf'))
        skyl1 = _f(row.get('skyl1'))
        alti = _f(row.get('alti'))
        skyc1 = (row.get('skyc1') or '').strip() or None
        wind_ms = None if sknt is None else round(sknt * KT_TO_MS, 2)
        gust_ms = None if gust is None else round(gust * KT_TO_MS, 2)
        gust_source = 'OBSERVED'
        if gust_ms is None:
            # 没有阵风报 = 没有阵风。用持续风回填，并留痕（模型卡里要写这一条）。
            gust_ms, gust_source = wind_ms, 'FALLBACK_WIND'
        cloud_base = None if skyl1 is None else round(skyl1 * FT_TO_M, 1)
        cloud_source = 'OBSERVED' if cloud_base is not None else 'MISSING'
        if cloud_base is None and skyc1 in ('CLR', 'SKC', 'NSC', 'NCD', 'CAVOK', 'M', '', None):
            # 晴空不报云底：给一个"高于任何低空决策阈值"的哨兵值，同样留痕。
            # `M` 是 ASOS 的"该要素未报"，在这些站点上它与 NSC/CAVOK 同义（实测核对过）。
            cloud_base, cloud_source = 5000.0, 'CLEAR_SENTINEL'
        rows.append({
            'station': station,
            'timeUtc': ts.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'epoch': int(ts.timestamp()),
            'visM': None if vsby is None else round(vsby * SM_TO_M, 1),
            'gustMs': gust_ms,
            'gustSource': gust_source,
            'windMs': wind_ms,
            'wdirDeg': _f(row.get('drct')),
            'tempC': None if tmpf is None else round((tmpf - 32) * 5 / 9, 2),
            'dewC': None if dwpf is None else round((dwpf - 32) * 5 / 9, 2),
            'cloudBaseM': cloud_base,
            'cloudSource': cloud_source,
            'skyCover': skyc1,
            'qnhHpa': None if alti is None else round(alti * 33.8639, 1),
        })
    return rows


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for station in STATIONS:
        for year in YEARS:
            body = fetch(station, year)
            got = parse(body, station)
            all_rows.extend(got)
            print(f'{station} {year}: {len(got)} rows', flush=True)
    all_rows.sort(key=lambda r: (r['station'], r['epoch']))

    fieldnames = ['station', 'timeUtc', 'epoch', 'visM', 'gustMs', 'gustSource', 'windMs',
                  'wdirDeg', 'tempC', 'dewC', 'cloudBaseM', 'cloudSource', 'skyCover', 'qnhHpa']
    series = OUT / 'series.csv'
    with series.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    total = len(all_rows)
    miss = {k: sum(1 for r in all_rows if r[k] is None) for k in
            ('visM', 'gustMs', 'windMs', 'tempC', 'dewC', 'cloudBaseM', 'qnhHpa')}
    digest = hashlib.sha256(series.read_bytes()).hexdigest()
    meta = {
        'version': 'metar-v1',
        'createdAt': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'source': HOST,
        'reportType': 3,
        'stations': STATIONS,
        'years': [min(YEARS), max(YEARS)],
        'rows': total,
        'perStation': {s: sum(1 for r in all_rows if r['station'] == s) for s in STATIONS},
        'missing': miss,
        'missingRate': {k: round(v / total, 4) for k, v in miss.items()},
        'gustSource': {k: sum(1 for r in all_rows if r['gustSource'] == k) for k in ('OBSERVED', 'FALLBACK_WIND')},
        'cloudSource': {k: sum(1 for r in all_rows if r['cloudSource'] == k) for k in ('OBSERVED', 'CLEAR_SENTINEL')},
        'units': {'visM': 'm', 'gustMs': 'm/s', 'windMs': 'm/s', 'tempC': 'C',
                  'dewC': 'C', 'cloudBaseM': 'm', 'qnhHpa': 'hPa'},
        'sha256': digest,
    }
    (OUT / 'dataset.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
