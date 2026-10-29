# -*- coding: utf-8 -*-
"""0.11.7 · 数据补齐：案例从 3 站扩到 4 站（补大连 ZYTL）。

## 为什么要补

案例原来只有 ZYTX / ZYCC / ZYHB（沈阳 / 长春 / 哈尔滨）。复测报告指出"雾区只在
沈阳周边"，而**大连当天实测 2800 m** —— 那是"偏低但不禁飞"的档，正好能把
"两档雾"讲清楚（沈阳 998 m 禁飞、大连 2800 m 偏低）。

## 数据从哪来

`data/training/metar/series.csv`（Iowa State ASOS 抄录，与训练集同一源）只有 3 站。
所以这里从 ASOS 现拉 ZYTL，**按 series.csv 完全相同的口径**换算，写成一个
**独立的补充 CSV**（`case-ZYTL-20250105.csv`），而不是往 series.csv 里追加。

**为什么不改 series.csv**：那是训练集，`model-v2-metrics.json` 的指标是基于 3 站算的。
往里加一站会让"模型指标"与"训练集"不再对应 —— 而那个不一致不会有任何报错。

## 一个必须记住的坑

ASOS 的 `day2` 参数是**排他**的：`day1=4&day2=5` 只到 1 月 4 日 23:00，**不含** 1 月 5 日。
第一次就因为这一点得出"ZYTL 在 00–06Z 没有报"的错误结论 —— 而真相是数据一直都在。
"""
import csv
import io
import json
import subprocess
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES = ROOT / 'data' / 'training' / 'metar' / 'series.csv'
EXTRA = ROOT / 'data' / 'training' / 'metar' / 'case-ZYTL-20250105.csv'
OUT = ROOT / 'data' / 'traffic' / 'cases' / 'fog-20250105.json'
BUILDER = ROOT / 'tools' / 'maintenance' / '_build_case_fog_20250105.py'

HISTORY_FROM = '2025-01-04T18:00:00Z'
WINDOW_TO = '2025-01-05T06:00:00Z'
FIELDS = ('station', 'timeUtc', 'epoch', 'visM', 'gustMs', 'gustSource', 'windMs', 'wdirDeg',
          'tempC', 'dewC', 'cloudBaseM', 'cloudSource', 'skyCover', 'qnhHpa')

MI_TO_M = 1609.344
KT_TO_MS = 0.514444
FT_TO_M = 0.3048
INHG_TO_HPA = 33.8639


def fetch(station: str) -> str:
    params = [
        ('station', station),
        ('data', 'vsby'), ('data', 'gust'), ('data', 'sknt'), ('data', 'drct'),
        ('data', 'skyl1'), ('data', 'skyc1'), ('data', 'tmpf'), ('data', 'dwpf'), ('data', 'alti'),
        ('year1', '2025'), ('month1', '1'), ('day1', '4'),
        ('year2', '2025'), ('month2', '1'), ('day2', '6'),   # day2 排他 -> 覆盖到 1/5 23:59
        ('tz', 'UTC'), ('format', 'onlycomma'), ('latlon', 'no'),
        ('missing', 'M'), ('trace', 'T'), ('direct', 'no'), ('report_type', '3'),
    ]
    url = 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?' + urllib.parse.urlencode(params)
    out = subprocess.run(['curl', '-s', '--noproxy', '*', '--max-time', '60', url],
                         capture_output=True, text=True, check=True)
    return out.stdout


def _f(value):
    if value in (None, '', 'M', 'T'):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def to_series_rows(station: str, raw: str):
    """按 `series.csv` 的口径逐字段换算。**口径必须与既有 3 站完全一致**，
    否则同一个站会出现两套值 —— 而两套值都"看起来对"。"""
    rows = []
    for rec in csv.DictReader(io.StringIO(raw)):
        iso = (rec.get('valid') or '').replace(' ', 'T') + ':00Z'
        if not (HISTORY_FROM <= iso <= WINDOW_TO):
            continue
        vis = _f(rec.get('vsby'))
        gust = _f(rec.get('gust'))
        sknt = _f(rec.get('sknt'))
        wind_ms = round(sknt * KT_TO_MS, 1) if sknt is not None else None
        gust_ms = round(gust * KT_TO_MS, 1) if gust is not None else wind_ms
        skyl = _f(rec.get('skyl1'))
        cloud_m = round(skyl * FT_TO_M, 1) if skyl is not None else 5000.0
        tmpf, dwpf, alti = _f(rec.get('tmpf')), _f(rec.get('dwpf')), _f(rec.get('alti'))
        rows.append({
            'station': station,
            'timeUtc': iso,
            'epoch': 0,  # 生成器不用它算窗口，留 0 并在下面补齐
            'visM': round(vis * MI_TO_M, 1) if vis is not None else None,
            'gustMs': gust_ms,
            'gustSource': 'OBSERVED' if gust is not None else 'FALLBACK_WIND',
            'windMs': wind_ms,
            'wdirDeg': _f(rec.get('drct')),
            'tempC': round((tmpf - 32) * 5 / 9, 1) if tmpf is not None else None,
            'dewC': round((dwpf - 32) * 5 / 9, 1) if dwpf is not None else None,
            'cloudBaseM': cloud_m,
            'cloudSource': 'OBSERVED' if skyl is not None else 'CLEAR_SENTINEL',
            'skyCover': rec.get('skyc1') if rec.get('skyc1') not in ('M', '') else 'NSC',
            'qnhHpa': round(alti * INHG_TO_HPA, 1) if alti is not None else None,
        })
    return rows


def main() -> int:
    raw = fetch('ZYTL')
    rows = to_series_rows('ZYTL', raw)
    if len(rows) < 10:
        raise SystemExit('ZYTL 只拿到 %d 条，时间窗内数据不足 —— 不生成（不编数据）' % len(rows))
    with EXTRA.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print('ZYTL 写入 %d 条 -> %s' % (len(rows), EXTRA.name))
    print('  时间窗 %s ~ %s' % (rows[0]['timeUtc'], rows[-1]['timeUtc']))
    print('  能见度 %s' % sorted({r['visM'] for r in rows}))

    # ---- 改生成器：站点列表 + 多文件读取 ----
    text = BUILDER.read_text(encoding='utf-8')
    if "STATIONS = ('ZYTX', 'ZYCC', 'ZYHB', 'ZYTL')" not in text:
        text = text.replace("STATIONS = ('ZYTX', 'ZYCC', 'ZYHB')",
                            "STATIONS = ('ZYTX', 'ZYCC', 'ZYHB', 'ZYTL')", 1)
    if 'EXTRA_SERIES' not in text:
        text = text.replace("SERIES = ROOT / 'data' / 'training' / 'metar' / 'series.csv'",
                            """SERIES = ROOT / 'data' / 'training' / 'metar' / 'series.csv'
# 0.11.7：训练集只有 3 站（模型指标基于它，不能动）。第 4 站（大连 ZYTL）单独存一份
# **只含本案例时间窗**的补充 CSV，由 `_extend_case_zy_tl.py` 从 ASOS 现拉。
EXTRA_SERIES = (ROOT / 'data' / 'training' / 'metar' / 'case-ZYTL-20250105.csv',)""", 1)
        text = text.replace("""    with SERIES.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle):""",
                            """    sources = (SERIES,) + tuple(p for p in EXTRA_SERIES if p.is_file())
    for source in sources:
      with source.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle):""", 1)
    BUILDER.write_text(text, encoding='utf-8')
    print('生成器已改：4 站 + 补充 CSV')

    # ---- 重新生成案例 ----
    run = subprocess.run(['python', str(BUILDER)], capture_output=True, text=True)
    print(run.stdout.strip() or run.stderr.strip()[:400])
    return 0 if run.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
