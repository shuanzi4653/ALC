# -*- coding: utf-8 -*-
"""生成历史回放案例 `fog-20250105`（0.11.3 · W-05）。

数据来源**只有一处**：`data/training/metar/series.csv`（清洗后的逐小时 METAR，
来源 Iowa State ASOS，与训练集同一个源）。这个脚本不做任何插值、不补任何值：
它只是把 2025-01-05 00:00Z 前后 7 小时的三站记录抄进案例文件。

窗口为什么是 00:00–06:00Z 而不是方案里写的 06:00–12:00Z：
方案自己写着"先拉全天的 ASOS 记录再定窗口，不要照抄这里的时段"。实测当天
沈阳（ZYTX）00:00–01:00Z 能见度 997.8 m（禁飞级）、02:00Z 1496.7 m、
03:00–05:00Z 1995.6 m、06:00–07:00Z 2993.4 m，云底 152–610 m，露点差 1–3 ℃ ——
辐射雾从清晨开始抬升。06:00Z 之后沈阳已回到 6–10 km，把窗口放在那里就拍不到雾。

用法：
    backend-python\\.venv\\Scripts\\python.exe tools/maintenance/_build_case_fog_20250105.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES = ROOT / 'data' / 'training' / 'metar' / 'series.csv'
# 0.11.7：训练集只有 3 站（模型指标基于它，不能动）。第 4 站（大连 ZYTL）单独存一份
# **只含本案例时间窗**的补充 CSV，由 `_extend_case_zy_tl.py` 从 ASOS 现拉。
EXTRA_SERIES = (ROOT / 'data' / 'training' / 'metar' / 'case-ZYTL-20250105.csv',)
OUT = ROOT / 'data' / 'traffic' / 'cases' / 'fog-20250105.json'

CASE_ID = 'fog-20250105'
STATIONS = ('ZYTX', 'ZYCC', 'ZYHB', 'ZYTL')
# 基准时刻 = 案例第一小时；历史窗口往前取 6 小时给模型算滞后量。
ANCHOR = '2025-01-05T00:00:00Z'
HISTORY_FROM = '2025-01-04T18:00:00Z'
WINDOW_TO = '2025-01-05T06:00:00Z'

FIELDS = ('station', 'timeUtc', 'epoch', 'visM', 'gustMs', 'gustSource', 'windMs', 'wdirDeg',
          'tempC', 'dewC', 'cloudBaseM', 'cloudSource', 'skyCover', 'qnhHpa')
NUMERIC = ('visM', 'gustMs', 'windMs', 'wdirDeg', 'tempC', 'dewC', 'cloudBaseM', 'qnhHpa')


def _num(value):
    if value in (None, '', 'M', 'T'):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    if not SERIES.is_file():
        raise SystemExit('缺少 %s，无法生成案例（不编数据）' % SERIES)
    rows = {station: [] for station in STATIONS}
    sources = (SERIES,) + tuple(p for p in EXTRA_SERIES if p.is_file())
    for source in sources:
      with source.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            station = row.get('station')
            if station not in rows:
                continue
            iso = row.get('timeUtc') or ''
            if not (HISTORY_FROM <= iso <= WINDOW_TO):
                continue
            item = {key: row.get(key) for key in FIELDS}
            for key in NUMERIC:
                item[key] = _num(item.get(key))
            # `epoch` 是 `nowcast.vector_for` 的输入（滞后量按它算时间差）。
            # 缺了它不会静默降级：predict_station 会直接 KeyError —— 这正是我们要的，
            # 一个"看起来有历史、其实算不出特征"的案例比没有案例更危险。
            item['epoch'] = int(_num(item.get('epoch')) or 0)
            rows[station].append(item)
    for station, items in rows.items():
        items.sort(key=lambda item: item['timeUtc'])
        if not items:
            raise SystemExit('%s 在 %s..%s 没有记录 —— 空案例不该写出来'
                             % (station, HISTORY_FROM, WINDOW_TO))

    # 历史**截到基准小时为止**：`predict_station` 拿 `history[-1]` 当"当前观测"，
    # 所以历史里一旦混进基准之后的小时，案例算出来的就会是那天早上雾散了以后的场
    # （实测踩到：history 写到 06:00Z，于是 997.8 m 的雾被 2993 m 的 06 时顶掉，
    # 首屏一句"可按计划运行"—— 案例存在，但拍的不是雾）。
    history = {station: [item for item in items if item['timeUtc'] <= ANCHOR]
               for station, items in rows.items()}
    frames = []
    for station, items in rows.items():
        for item in items:
            if item['timeUtc'] < ANCHOR:
                continue
            slot = next((frame for frame in frames if frame['t'] == item['timeUtc']), None)
            if slot is None:
                slot = {'t': item['timeUtc']}
                frames.append(slot)
            slot[station] = {
                'visM': item['visM'], 'gustMs': item['gustMs'],
                'dewSpread': (None if item['tempC'] is None or item['dewC'] is None
                              else round(item['tempC'] - item['dewC'], 1)),
                'cloudBaseM': item['cloudBaseM'],
            }
    frames.sort(key=lambda frame: frame['t'])
    if not frames:
        raise SystemExit('窗口内没有任何逐时帧')

    payload = {
        'caseId': CASE_ID,
        'label': '历史回放 · 2025-01-05 沈阳大雾',
        'kind': 'HISTORICAL_REPLAY',
        'timeBase': ANCHOR,
        'displayTz': 'Asia/Shanghai',
        'window': {'from': ANCHOR, 'to': WINDOW_TO},
        'stations': list(STATIONS),
        'history': history,
        'frames': frames,
        'source': {
            'metar': 'Iowa State ASOS（与训练集同一源）',
            'file': 'data/training/metar/series.csv',
            'retrieved': '本文件由 tools/maintenance/_build_case_fog_20250105.py 从上述 CSV 抄录，未做插值',
        },
        'note': '天气为 METAR 实测；班次骨架由平台按固定种子生成；结论由系统按本帧观测算出。',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    lowest = min((frame[s]['visM'] for frame in frames for s in STATIONS
                  if frame.get(s) and frame[s].get('visM') is not None), default=None)
    print('wrote %s · %d 帧 · 最低能见度 %s m' % (OUT.relative_to(ROOT), len(frames), lowest))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
