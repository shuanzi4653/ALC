#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端云同源对拍：同一批 1000 组特征，Python 参考实现 vs 端侧 C 实现，逐条比 p。

两种取端侧结果的路径
====================
1. 真板子：
       python tools/edge-export/pair_check.py --port COM7 --baud 921600
   串口是**一问一答**的：发一行 26 个数，等一条 `RES` 回来再发下一条。
   一次性把 1000 行灌进去会撑爆 ESP32 的 256 字节 UART 接收缓冲，
   丢行之后你得到的是"对拍失败"的假象，所以这里坚持锁步。
2. Plan B（没有板子 / 串口没枚举）：
       edge_x86.exe cases.csv > edge_x86_log.txt
       python tools/edge-export/pair_check.py --input edge_x86_log.txt
   编的是**同一份** edge_infer.c，只换了编译目标。对外表述写
   "同一份 C 代码在等价编译目标上验证"，这句话是可辩护的。

判定口径
========
- 主指标：`max|Δp|`，容差 **1e-4**（端侧 float32 vs Python float64 的合理量级是 1e-7，
  留 1e-4 是为了不把"最后一个 ulp"当成 bug，同时又能抓住叶片翻边的错）。
- 超差组数：`|Δp| > 1e-4` 的条数，必须是 0。若不是 0，报告里必须逐条列出，
  并解释是阈值边界（特征恰好在阈值上）还是真的实现走样。
- 副指标：`p>=0.3` 的判决一致率（模型 operatingThreshold），以及校准后概率的一致性。

    python tools/edge-export/pair_check.py --input edge_x86_log.txt
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / 'out'
MODEL = ROOT / 'models' / 'ml-v2-vis3k.json'
TOLERANCE = 1e-4
OPERATING_THRESHOLD = 0.3


def f32(value: float) -> float:
    """量化成 float32 再以 float64 返回。

    为什么读用例之后必须走这一道：端侧只有 float32，cases.csv 里写的是 float32 的最短
    round-trip 十进制串（比如 "9.4" 代表 float32 的 9.3999996185）。Python 直接
    `float("9.4")` 得到的是 float64 的 9.4，与端侧输入差 3.8e-7 —— 这个差足以让叶子翻边。
    不量化就等于"拿两组不同的输入比结果"，对拍会假失败（第一轮 40 组超差就是这么来的）。
    """
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


# --------------------------------------------------------------------------- 读用例

def load_cases(path: Path) -> Tuple[List[str], List[List[float]]]:
    names: List[str] = []
    vectors: List[List[float]] = []
    for line_number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        text = raw.strip()
        if not text:
            continue
        parts = [piece.strip() for piece in text.split(',')]
        if not names:
            names = parts  # 第一行是表头
            continue
        if len(parts) != len(names):
            raise SystemExit('第 %d 行有 %d 列，表头是 %d 列 —— 用例文件被改坏了' % (
                line_number, len(parts), len(names)))
        vectors.append([f32(piece) for piece in parts])
    return names, vectors


# --------------------------------------------------------------------------- 端侧结果

def parse_edge_log(path: Path) -> Tuple[List[float], List[float], List[float], Dict[str, str]]:
    """解析固件/x86 宿主输出。返回 (p, p_cal, us, 头信息)。"""
    probabilities: List[float] = []
    calibrated: List[float] = []
    micros: List[float] = []
    header: Dict[str, str] = {}
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        text = raw.strip()
        if not text:
            continue
        if text.startswith('#'):
            body = text[1:].strip()
            if body.startswith('MODEL'):
                fields = body.split()
                header['model'] = ' '.join(fields[1:])
            elif body.startswith('SUMMARY'):
                header['summary'] = body
            elif body:
                header.setdefault('check', body)
            continue
        fields = text.split()
        if len(fields) < 4 or fields[0] != 'RES':
            continue
        probabilities.append(float(fields[2]))
        calibrated.append(float(fields[3]))
        micros.append(float(fields[4]))
    return probabilities, calibrated, micros, header


def collect_from_serial(port: str, baud: int, vectors: List[List[float]],
                        names: List[str], timeout: float) -> Tuple[List[float], List[float], List[float], Dict[str, str]]:
    try:
        import serial  # noqa: WPS433 - 只有真板子时才需要
    except ImportError:
        raise SystemExit('没有装 pyserial：先 `python -m pip install pyserial`，'
                         '或者改用 --input <日志文件> 的 Plan B 流程。')

    probabilities: List[float] = []
    calibrated: List[float] = []
    micros: List[float] = []
    header: Dict[str, str] = {}

    with serial.Serial(port=port, baudrate=baud, timeout=timeout) as link:
        link.reset_input_buffer()
        deadline = time.time() + max(timeout, 20.0)
        # 先收开机自检，直到 READY
        while time.time() < deadline:
            line = link.readline().decode('utf-8', errors='replace').strip()
            if not line:
                continue
            if line.startswith('#'):
                body = line[1:].strip()
                if body.startswith('MODEL'):
                    header['model'] = ' '.join(body.split()[1:])
                elif body:
                    header.setdefault('check', body)
            if line.startswith('# READY'):
                break

        for index, vector in enumerate(vectors, start=1):
            link.write((','.join('%.9g' % value for value in vector) + '\n').encode('ascii'))
            link.flush()
            answer = ''
            limit = time.time() + timeout
            while time.time() < limit:
                candidate = link.readline().decode('utf-8', errors='replace').strip()
                if not candidate:
                    continue
                if candidate.startswith('RES'):
                    answer = candidate
                    break
                if candidate.startswith('#'):
                    body = candidate[1:].strip()
                    if body.startswith('SUMMARY'):
                        header['summary'] = body
            if not answer:
                raise SystemExit('第 %d 条用例等不到应答（%s 秒超时）。'
                                 '检查波特率是否与固件一致、串口是否被别的程序占用。' % (index, timeout))
            fields = answer.split()
            probabilities.append(float(fields[2]))
            calibrated.append(float(fields[3]))
            micros.append(float(fields[4]))
            if index % 100 == 0:
                print('  已收 %d/%d 条' % (index, len(vectors)), flush=True)
    return probabilities, calibrated, micros, header


# --------------------------------------------------------------------------- 统计

def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def describe(values: List[float]) -> Dict[str, float]:
    return {
        'min': percentile(values, 0.0),
        'p50': percentile(values, 0.5),
        'p95': percentile(values, 0.95),
        'max': percentile(values, 1.0),
        'mean': (sum(values) / len(values)) if values else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='端云同源对拍')
    parser.add_argument('--cases', default=str(HERE / 'cases.csv'))
    parser.add_argument('--model', default=str(MODEL))
    parser.add_argument('--input', help='端侧输出日志（Plan B / 已落盘的串口日志）')
    parser.add_argument('--port', help='串口名，例如 COM7')
    parser.add_argument('--baud', type=int, default=921600)
    parser.add_argument('--timeout', type=float, default=5.0)
    parser.add_argument('--out-dir', default=str(OUT_DIR))
    parser.add_argument('--tag', default='', help='输出文件后缀，便于区分多次实验')
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.is_file():
        print('[FAIL] 找不到用例文件 %s，先跑 gen_cases.py' % cases_path)
        return 2
    names, vectors = load_cases(cases_path)
    if not vectors:
        print('[FAIL] 用例文件里没有数据行')
        return 2

    # ---- Python 参考实现
    sys.path.insert(0, str(ROOT / 'backend-python'))
    from ml.forest import Forest  # noqa: WPS433
    payload = json.loads(Path(args.model).read_text(encoding='utf-8'))
    forest = Forest(payload)
    if list(payload['featureNames']) != names:
        print('[FAIL] 用例表头与模型 featureNames 不一致（顺序错位会让预测静默变错）')
        print('  用例: %s' % ','.join(names))
        print('  模型: %s' % ','.join(payload['featureNames']))
        return 3

    p_py: List[float] = []
    us_py: List[float] = []
    for vector in vectors:
        started = time.perf_counter()
        result = forest.predict(vector)
        us_py.append((time.perf_counter() - started) * 1e6)
        p_py.append(float(result['probabilitiesExact']['POS']))

    # ---- 端侧结果
    if args.input:
        p_edge, p_edge_cal, us_edge, header = parse_edge_log(Path(args.input))
        source_name = Path(args.input).name
    elif args.port:
        print('串口取数：%s @ %d' % (args.port, args.baud), flush=True)
        p_edge, p_edge_cal, us_edge, header = collect_from_serial(
            args.port, args.baud, vectors, names, args.timeout)
        source_name = 'serial:%s' % args.port
    else:
        print('[FAIL] 二选一：--input <日志> 或 --port <COMx>')
        return 2

    if len(p_edge) != len(p_py):
        print('[FAIL] 端侧回来 %d 条，用例 %d 条 —— 有丢行，先解决丢行再谈一致性'
              % (len(p_edge), len(p_py)))
        return 4

    # ---- 校准（nowcast._interp 的语义），端侧 edge_calibrate 应与它一致
    def interp(x: float, xs: List[float], ys: List[float]) -> float:
        if not xs:
            return x
        if x <= xs[0]:
            return float(ys[0])
        if x >= xs[-1]:
            return float(ys[-1])
        for i in range(1, len(xs)):
            if x <= xs[i]:
                span = xs[i] - xs[i - 1]
                if span <= 0:
                    return float(ys[i])
                ratio = (x - xs[i - 1]) / span
                return float(ys[i - 1] + ratio * (ys[i] - ys[i - 1]))
        return float(ys[-1])

    calibration = payload.get('calibration') or {'x': [], 'y': []}
    p_py_cal = [interp(value, [float(v) for v in calibration.get('x') or []],
                       [float(v) for v in calibration.get('y') or []]) for value in p_py]

    # ---- 逐条比较
    deltas = [abs(a - b) for a, b in zip(p_py, p_edge)]
    deltas_cal = [abs(a - b) for a, b in zip(p_py_cal, p_edge_cal)]
    over = [(index + 1, p_py[index], p_edge[index], deltas[index])
            for index in range(len(deltas)) if deltas[index] > TOLERANCE]
    same_level = sum(1 for a, b in zip(p_py, p_edge)
                     if (a >= OPERATING_THRESHOLD) == (b >= OPERATING_THRESHOLD))

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ('-' + args.tag) if args.tag else ''
    detail_path = out_dir / ('parity-%s%s.csv' % (stamp, suffix))
    summary_path = out_dir / ('parity-%s%s.json' % (stamp, suffix))

    lines = ['seq,p_py,p_edge,abs_delta,p_cal_py,p_cal_edge,abs_delta_cal,us_edge,us_py']
    for index in range(len(p_py)):
        lines.append('%d,%.9f,%.9f,%.3e,%.9f,%.9f,%.3e,%.0f,%.1f' % (
            index + 1, p_py[index], p_edge[index], deltas[index],
            p_py_cal[index], p_edge_cal[index], deltas_cal[index],
            us_edge[index], us_py[index]))
    detail_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    summary: Dict[str, Any] = {
        'generatedAt': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'cases': len(p_py),
        'casesFile': cases_path.name,
        'edgeSource': source_name,
        'edgeHeader': header,
        'tolerance': TOLERANCE,
        'deltaRaw': {
            'max': max(deltas),
            'mean': sum(deltas) / len(deltas),
            'rms': math.sqrt(sum(d * d for d in deltas) / len(deltas)),
            'p50': percentile(deltas, 0.5),
            'p95': percentile(deltas, 0.95),
            'over': len(over),
        },
        'deltaCalibrated': {
            'max': max(deltas_cal),
            'mean': sum(deltas_cal) / len(deltas_cal),
            'over': sum(1 for d in deltas_cal if d > TOLERANCE),
        },
        'levelAgreement': {
            'threshold': OPERATING_THRESHOLD,
            'agree': same_level,
            'rate': same_level / len(p_py),
            'positivePy': sum(1 for value in p_py if value >= OPERATING_THRESHOLD),
            'positiveEdge': sum(1 for value in p_edge if value >= OPERATING_THRESHOLD),
        },
        'pDistribution': describe(p_py),
        'timingEdgeUs': describe(us_edge),
        'timingPythonUs': describe(us_py),
        'overTolerance': [{'seq': seq, 'p_py': a, 'p_edge': b, 'delta': d} for seq, a, b, d in over[:20]],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    # ---- 屏显（报告里的数字直接从这里抄）
    print('')
    print('端侧数据来源   : %s' % source_name)
    if header.get('model'):
        print('端侧自报模型   : %s' % header['model'])
    if header.get('check'):
        print('端侧自检       : %s' % header['check'])
    if header.get('summary'):
        print('端侧汇总       : %s' % header['summary'])
    print('用例数         : %d' % len(p_py))
    print('')
    print('原始概率 p(POS) 一致性（容差 %.0e）：' % TOLERANCE)
    print('  max|Δp|      : %.3e   %s' % (max(deltas), 'PASS' if max(deltas) <= TOLERANCE else 'FAIL'))
    print('  mean|Δp|     : %.3e' % (sum(deltas) / len(deltas)))
    print('  rms|Δp|      : %.3e' % summary['deltaRaw']['rms'])
    print('  p50 / p95    : %.3e / %.3e' % (percentile(deltas, 0.5), percentile(deltas, 0.95)))
    print('  超差组数     : %d / %d' % (len(over), len(deltas)))
    if over:
        print('  超差明细（前 10 条）：')
        for seq, a, b, d in over[:10]:
            print('    seq=%d  p_py=%.6f  p_edge=%.6f  Δ=%.3e' % (seq, a, b, d))
    print('')
    print('校准后概率一致性（nowcast._interp 口径）：')
    print('  max|Δp_cal|  : %.3e   超差 %d 组' % (max(deltas_cal),
                                                 sum(1 for d in deltas_cal if d > TOLERANCE)))
    print('')
    print('判决一致率（p >= %.1f 视为 POS）：%d/%d = %.4f%%'
          % (OPERATING_THRESHOLD, same_level, len(p_py), 100.0 * same_level / len(p_py)))
    print('  Python 侧 POS 组数 %d，端侧 POS 组数 %d'
          % (summary['levelAgreement']['positivePy'], summary['levelAgreement']['positiveEdge']))
    print('')
    print('p 分布（Python 侧）：min %.6f / p50 %.6f / p95 %.6f / max %.6f'
          % tuple(summary['pDistribution'][key] for key in ('min', 'p50', 'p95', 'max')))
    print('单次耗时（端侧）：min %.0f / p50 %.0f / mean %.1f / max %.0f us'
          % (summary['timingEdgeUs']['min'], summary['timingEdgeUs']['p50'],
             summary['timingEdgeUs']['mean'], summary['timingEdgeUs']['max']))
    print('单次耗时（Python 参考，同一台 PC）：mean %.1f us' % summary['timingPythonUs']['mean'])
    print('')
    print('明细       : %s' % detail_path)
    print('汇总 JSON  : %s' % summary_path)
    print('')
    if max(deltas) <= TOLERANCE:
        print('[PASS] 端云同源：%d 组用例全部在 %.0e 容差内。' % (len(deltas), TOLERANCE))
        return 0
    print('[FAIL] 有 %d 组超过容差，先查是不是特征值正好压在阈值上，再查实现。' % len(over))
    return 1


if __name__ == '__main__':
    sys.exit(main())
