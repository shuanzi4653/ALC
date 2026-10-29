# -*- coding: utf-8 -*-
"""0.10.1 数据 ③ DeepSeek 标注（断点续跑、并发、幂等缓存）。

四条口径：
1. **给公开判据，不给规则引擎的权重与算分**。给了惩罚分与 100 分累减公式，模型就只是在
   复述规则；而本方案要回答的恰恰是"模型判断与规则判断是否一致、分歧在哪"。
   prompt 由 `config/labels-v1.json` **生成**（单一来源），改判据不用改脚本。
2. **temperature=0 + 固定 seed + json_object**：同一输入两次调用必须同一答案，
   否则样本被重标一次就换了标签，训练集不可复现。
3. **幂等缓存**：键 = sha256(sampleId + promptVersion + model + temperature)，
   命中即复用。跑一半断掉，重跑只补缺的那部分。
4. **失败不静默**：重试 3 次仍失败写 `ANNOTATE_FAILED` 单列，绝不并入任何一档。
"""
import argparse
import concurrent.futures as futures
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data' / 'training'
CACHE = DATA / 'annotate-cache'
SAMPLES = DATA / 'samples-v1.jsonl'
OUT = DATA / 'labels-v1.jsonl'
REPORT = DATA / 'annotate-v1.json'

PROMPT_VERSION = 'labels-v1-2026-10-17'
MODEL_DEFAULT = 'deepseek-chat'


def load_cfg():
    cfg = yaml.safe_load(io.open(ROOT / 'config' / 'application.yml', encoding='utf-8'))
    ds = cfg['deepseek']
    return ds['api-key'], ds.get('base-url', 'https://api.deepseek.com')


def build_rubric(spec):
    """从 labels-v1.json 生成判据文字。改阈值只改 JSON，不动脚本。"""
    lines = ['你是低空飞行（eVTOL / 无人机）气象放行判定的复核员。',
             '给你一小时的实况/短期预报气象要素，判断该小时在该城市执行飞行的气象风险档位。',
             '只看气象要素，不要推测航线或机型。', '',
             '档位（必须四选一，用英文代码）：',
             '- FIT     适飞：各要素都在运行包线内。',
             '- CAUTION 注意：存在轻度不利要素，可飞但需加强监控、留足余度。',
             '- DANGER  危险：存在明显不利要素，建议推迟、改时隙或改航。',
             '- BAN     禁飞：存在使飞行不可执行的要素。', '',
             '判定所依据的判据（只作判据，**不要加权求和、不要计算分数**）：']
    for f in spec['factors']:
        if f.get('direction') == 'none':
            continue
        b = f['bands']
        if f.get('direction') == 'high':
            lines.append(f"- {f['label']}（{f['unit']}）：≤{b['fit']:g} 适飞；"
                         f"{b['fit']:g}–{b['caution']:g} 注意；{b['caution']:g}–{b['danger']:g} 危险；"
                         f">{b['danger']:g} 禁飞。")
        elif f.get('direction') == 'low':
            lines.append(f"- {f['label']}（{f['unit']}）：≥{b['fit']:g} 适飞；"
                         f"{b['caution']:g}–{b['fit']:g} 注意；{b['danger']:g}–{b['caution']:g} 危险；"
                         f"<{b['danger']:g} 禁飞。")
        else:
            lines.append(f"- {f['label']}（{f['unit']}）：{b['warnLow']:g}–{b['warnHigh']:g} 适飞；"
                         f"超出该区间但仍在 {b['banLow']:g}–{b['banHigh']:g} 内为注意；"
                         f"超出 {b['banLow']:g}–{b['banHigh']:g} 为禁飞。")
    lines += [
        "- 阵风与平均风之比（阵风因子，仅当平均风 ≥3 m/s）：>2.6 至少注意；>3.2 危险。",
        "- 结冰迹象：温度 <2 ℃ 且相对湿度 ≥90%，至少注意。",
        '',
        '多要素同时不利时取更保守的一档；**漏报危险比误报注意代价更高**。',
        '',
        '严格输出 JSON，不要输出任何其它文字：',
        '{"level":"FIT|CAUTION|DANGER|BAN","confidence":0.0-1.0,'
        '"top3Factors":["..."],"rationale":"不超过80字的中文理由，必须引用具体数值",'
        '"needsHuman":true|false}',
        'needsHuman 为 true 仅当你认为两位有经验的签派员也可能给出不同档位。',
    ]
    return '\n'.join(lines)


def user_msg(r):
    def fmt(v, unit, nd=1):
        return '缺测' if v is None else f'{v:.{nd}f} {unit}'
    return (
        f"城市：{r['city']}（东北地区）\n"
        f"当地时间：{r['timeLocal']}（{r['hour']} 时，东亚时区）\n"
        f"温度：{fmt(r['temperatureC'], '℃')}\n"
        f"相对湿度：{fmt(r['rhPct'], '%', 0)}\n"
        f"降水量：{fmt(r['precipMmh'], 'mm/h', 1)}\n"
        f"降雪量：{fmt(r['snowCmh'], 'cm/h', 1)}\n"
        f"云量：{fmt(r['cloudPct'], '%', 0)}\n"
        f"海平面气压：{fmt(r['pressureHpa'], 'hPa')}\n"
        f"10 米平均风速：{fmt(r['windMps'], 'm/s')}\n"
        f"阵风：{fmt(r['gustMps'], 'm/s')}\n"
        f"能见度：{fmt(r['visibilityM'], 'm', 0)}\n"
        f"天气现象代码（WMO weather_code）：{r['weatherCode']}\n"
        "请按给定档位判定并输出 JSON。"
    )


def cache_key(sample_id, model):
    raw = f'{sample_id}|{PROMPT_VERSION}|{model}|0'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def call(key, base, model, rubric, usr, timeout=90):
    body = json.dumps({
        'model': model,
        'messages': [{'role': 'system', 'content': rubric}, {'role': 'user', 'content': usr}],
        'temperature': 0,
        'max_tokens': 400,
        'response_format': {'type': 'json_object'},
        'seed': 20261017,
    }).encode('utf-8')
    req = urllib.request.Request(
        base.rstrip('/') + '/chat/completions', data=body,
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode('utf-8'))
    dt = time.time() - t0
    msg = payload['choices'][0]['message']['content']
    usage = payload.get('usage') or {}
    return msg, dt, usage


def parse_json(text):
    t = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def annotate_one(r, key, base, model, rubric):
    ck = cache_key(r['sampleId'], model)
    cf = CACHE / f'{ck}.json'
    if cf.is_file():
        rec = json.load(io.open(cf, encoding='utf-8'))
        rec['fromCache'] = True
        return rec

    last = None
    for attempt in range(3):
        try:
            text, dt, usage = call(key, base, model, rubric, user_msg(r))
            obj = parse_json(text)
            rec = {
                'sampleId': r['sampleId'],
                'model': model,
                'promptVersion': PROMPT_VERSION,
                'level': obj.get('level'),
                'confidence': obj.get('confidence'),
                'top3Factors': obj.get('top3Factors'),
                'rationale': obj.get('rationale'),
                'needsHuman': obj.get('needsHuman'),
                'latencyS': round(dt, 2),
                'tokensIn': usage.get('prompt_tokens', 0),
                'tokensOut': usage.get('completion_tokens', 0),
            }
            cf.parent.mkdir(parents=True, exist_ok=True)
            with io.open(cf, 'w', encoding='utf-8', newline='\n') as fh:
                json.dump(rec, fh, ensure_ascii=False)
            rec['fromCache'] = False
            return rec
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    return {'sampleId': r['sampleId'], 'level': 'ANNOTATE_FAILED', 'error': str(last),
            'model': model, 'promptVersion': PROMPT_VERSION, 'fromCache': False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 条（调试用）')
    ap.add_argument('--concurrency', type=int, default=6)
    ap.add_argument('--model', default=MODEL_DEFAULT)
    args = ap.parse_args()

    key, base = load_cfg()
    spec = json.load(io.open(ROOT / 'config' / 'labels-v1.json', encoding='utf-8'))
    rubric = build_rubric(spec)
    rows = [json.loads(l) for l in io.open(SAMPLES, encoding='utf-8') if l.strip()]
    if args.limit:
        rows = rows[:args.limit]
    print(f'[INFO] 样本 {len(rows)} 条 / model={args.model} / 并发 {args.concurrency}')

    lock = threading.Lock()
    results, done = [], [0]

    def work(r):
        rec = annotate_one(r, key, base, args.model, rubric)
        with lock:
            results.append(rec)
            done[0] += 1
            if done[0] % 50 == 0 or done[0] == len(rows):
                print(f'  ... {done[0]}/{len(rows)}', flush=True)
        return rec

    t0 = time.time()
    with futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(work, rows))
    wall = time.time() - t0

    order = {r['sampleId']: i for i, r in enumerate(rows)}
    results.sort(key=lambda x: order.get(x['sampleId'], 0))

    tok_in = sum(r.get('tokensIn') or 0 for r in results)
    tok_out = sum(r.get('tokensOut') or 0 for r in results)
    failed = [r for r in results if r['level'] == 'ANNOTATE_FAILED']
    cached = sum(1 for r in results if r.get('fromCache'))
    lat = sorted(r.get('latencyS') for r in results if r.get('latencyS'))

    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    report = {
        'promptVersion': PROMPT_VERSION,
        'model': args.model,
        'samples': len(results),
        'annotated': len(results) - len(failed),
        'failed': len(failed),
        'failedIds': [r['sampleId'] for r in failed],
        'fromCache': cached,
        'tokensIn': tok_in,
        'tokensOut': tok_out,
        'wallSeconds': round(wall, 1),
        'latencyMedian': round(lat[len(lat) // 2], 2) if lat else None,
        'latencyMax': round(lat[-1], 2) if lat else None,
        'concurrency': args.concurrency,
        'levels': {},
    }
    for r in results:
        report['levels'][r['level']] = report['levels'].get(r['level'], 0) + 1
    with io.open(REPORT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f'[OK] 标注 {report["annotated"]}/{report["samples"]}，失败 {report["failed"]}，'
          f'缓存命中 {cached}')
    print(f'[OK] token 输入 {tok_in} / 输出 {tok_out}；墙钟 {report["wallSeconds"]}s；'
          f'中位延迟 {report["latencyMedian"]}s')
    print('[OK] 档位分布 ' + ' '.join(f'{k}={v}' for k, v in sorted(report['levels'].items())))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
