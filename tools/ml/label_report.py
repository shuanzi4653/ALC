# -*- coding: utf-8 -*-
"""0.10.1 数据 ④ 判据档位 + 与 DeepSeek 的一致性 + 人工仲裁抽样。

为什么训练标签最终取**判据**而不是取 DeepSeek 的档位：
DeepSeek 这一轮 1133 条的实测分布是 BAN 34% / DANGER 45% / CAUTION 19% / **FIT 2.4%**，
而判据给的是四档同量级。逐条看它的 rationale 就明白了 —— 它把"7.5 m/s，接近 8 m/s 阈值"
判成 CAUTION（判据里 7.5 < 8 就是 FIT），属于**边界更保守的一档偏移**，不是随机噪声：
它几乎不给 FIT。

如果直接拿这套标签训练，模型会学成"几乎不判适飞"，而 FIT 档只有 27 条也没法训练。
但这不代表 DeepSeek 那 1133 条白跑：它现在是**独立的第二标注员**，用来量
"我们这套判据能不能被别人按同样的读法复现"。这符合本仓的口径 —— 验证独立于被验证对象。
分歧样本进人工仲裁，仲裁结果单独存，不覆盖任何一方。
"""
import io
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from ml import labels as L  # noqa: E402

DATA = ROOT / 'data' / 'training'
LEVELS = ['FIT', 'CAUTION', 'DANGER', 'BAN']


def load():
    samples = {}
    for line in io.open(DATA / 'samples-v1.jsonl', encoding='utf-8'):
        if line.strip():
            r = json.loads(line)
            samples[r['sampleId']] = r
    ds = {}
    for line in io.open(DATA / 'labels-v1.jsonl', encoding='utf-8'):
        if line.strip():
            r = json.loads(line)
            ds[r['sampleId']] = r
    return samples, ds


def snapshot(row):
    return {
        'windSpeed': row['windMps'], 'windGust': row['gustMps'],
        'precipMmh': row['precipMmh'], 'visibilityM': row['visibilityM'],
        'tempC': row['temperatureC'], 'rhPct': row['rhPct'],
    }


def kappa(a, b):
    ids = [k for k in a if k in b and a[k] in LEVELS and b[k] in LEVELS]
    n = len(ids)
    if not n:
        return 0.0, 0.0, 0
    idx = {lv: i for i, lv in enumerate(LEVELS)}
    obs = [[0] * 4 for _ in range(4)]
    for k in ids:
        obs[idx[a[k]]][idx[b[k]]] += 1
    po = sum(obs[i][i] for i in range(4)) / n
    ra = [sum(obs[i]) / n for i in range(4)]
    cb = [sum(obs[i][j] for i in range(4)) / n for j in range(4)]
    pe = sum(ra[i] * cb[i] for i in range(4))
    # 二次加权 κ：相邻档的分歧按距离平方打折 —— 这里的分歧几乎都是相邻档，
    # 不加权会把"差一档"和"差三档"算成一样糟。
    num = sum(((i - j) ** 2) * obs[i][j] for i in range(4) for j in range(4))
    den = sum(((i - j) ** 2) * ra[i] * cb[j] * n for i in range(4) for j in range(4))
    kw = 1 - num / den if den else 0.0
    return round(po, 4), round(kw, 4), n


def main():
    samples, ds = load()
    spec = L.load_spec()

    rows, spec_levels = [], {}
    for sid, row in samples.items():
        out = spec.label(snapshot(row))
        spec_levels[sid] = out['level']
        rows.append((sid, row, out))

    dist_spec = Counter(spec_levels.values())
    dist_ds = Counter(v['level'] for v in ds.values())
    total = len(rows)
    print('[判据] %s' % dict(dist_spec))
    print('[DS  ] %s' % dict(dist_ds))

    po, kw, n = kappa(spec_levels, {k: v['level'] for k, v in ds.items()})
    print('[一致性] 判据 vs DeepSeek：n=%d 一致率 %.4f 二次加权 κ %.4f' % (n, po, kw))

    # 分歧矩阵：行=判据，列=DS
    idx = {lv: i for i, lv in enumerate(LEVELS)}
    matrix = [[0] * 4 for _ in range(4)]
    for sid, level in spec_levels.items():
        if sid in ds and ds[sid]['level'] in LEVELS:
            matrix[idx[level]][idx[ds[sid]['level']]] += 1
    print('[矩阵] 行=判据 列=DeepSeek')
    for i, lv in enumerate(LEVELS):
        print('   %-8s %s' % (lv, matrix[i]))

    # 人工仲裁抽样：每档 12 条，优先取"判据与 DS 分歧"的
    rnd = random.Random(20261017)
    picked = []
    for lv in LEVELS:
        pool = [sid for sid, level in spec_levels.items() if level == lv]
        disagree = [sid for sid in pool if ds.get(sid, {}).get('level') != lv]
        agree = [sid for sid in pool if ds.get(sid, {}).get('level') == lv]
        rnd.shuffle(disagree)
        rnd.shuffle(agree)
        take = disagree[:8] + agree[:4]
        picked.extend(take[:12])

    with io.open(DATA / 'adjudication-sheet.jsonl', 'w', encoding='utf-8', newline='\n') as f:
        for sid in picked:
            row = samples[sid]
            f.write(json.dumps({
                'sampleId': sid,
                'city': row['city'], 'timeLocal': row['timeLocal'],
                'season': row['season'], 'scenario': row['scenario'],
                'tempC': row['temperatureC'], 'rhPct': row['rhPct'],
                'precipMmh': row['precipMmh'], 'snowCmh': row['snowCmh'],
                'cloudPct': row['cloudPct'], 'windMps': row['windMps'],
                'gustMps': row['gustMps'], 'visibilityM': row['visibilityM'],
                'specLevel': spec_levels[sid],
                'dsLevel': ds.get(sid, {}).get('level'),
                'needLabel': '请填 FIT / CAUTION / DANGER / BAN',
            }, ensure_ascii=False) + '\n')

    print('[OK] 仲裁表 %d 条 -> %s' % (len(picked), DATA / 'adjudication-sheet.jsonl'))

    meta = {
        'specVersion': spec.version,
        'samples': total,
        'specDistribution': {k: dist_spec.get(k, 0) for k in LEVELS},
        'dsDistribution': {k: dist_ds.get(k, 0) for k in LEVELS},
        'agreement': {'n': n, 'raw': po, 'weightedKappa': kw},
        'matrix': matrix,
    }
    with io.open(DATA / 'label-agreement.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
