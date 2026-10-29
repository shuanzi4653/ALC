"""量「一份计划在 Python 里占多少内存」—— 这是 JOBS 上限该设几条的唯一依据。

代码注释里写着「约 110 MB（tracemalloc 实测）」，但那是早前量的。本探针重测一遍，
并**同时**给出两份独立读数：
  · RSS 增量      —— 操作系统看到的工作集（含 numpy 缓冲、shapely 几何）
  · tracemalloc   —— Python 分配器看到的字节（不含 C 扩展内部 malloc）

两者都量，是因为它们回答的不是同一个问题：RSS 决定「服务器还剩多少内存」，
tracemalloc 决定「哪一行的数据结构该瘦身」。

用法（cwd = backend-python，必须是这个 cwd，`.run/traffic` 相对仓库根）：
    ./.venv/Scripts/python.exe ../tools/maintenance/_probe_plan_memory.py
"""
from __future__ import annotations

import gc
import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))


def rss_mb() -> float:
    """当前进程 RSS（MB）。64 位下必须设 argtypes，否则参数被截断、函数静默返回 0。"""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    fn = ctypes.windll.kernel32.K32GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return -1.0
    return pmc.WorkingSetSize / 1048576


def main() -> int:
    print('=' * 74)
    print('一份计划的内存成本（决定 JOBS 上限）')
    print('=' * 74)
    print(f'空解释器 RSS                {rss_mb():8.1f} MB')

    import json
    from traffic import service

    print(f'import traffic.* 后 RSS     {rss_mb():8.1f} MB')
    base_rss = rss_mb()

    # 冷启动一遍（第一次含 numpy/shapely 的懒初始化，单列出来免得算进"每份成本"）
    t0 = time.time()
    tracemalloc.start()
    plan = service.simulate(seed=42, scenario='clear', weather_mode='virtual')
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    first_rss = rss_mb()
    print(f'\n[第 1 次] simulate(42, clear, virtual)  {time.time() - t0:.1f}s')
    print(f'  tracemalloc 常驻          {cur / 1048576:8.1f} MB')
    print(f'  tracemalloc 峰值          {peak / 1048576:8.1f} MB')
    print(f'  RSS 增量（含库懒初始化）  {first_rss - base_rss:8.1f} MB  → RSS {first_rss:.1f} MB')

    # 结构分解：哪一块最大
    print(f'\n[结构] 各字段体量（JSON 字节，反映真实数据量）')
    total_json = 0
    for key in sorted(plan.keys()):
        value = plan[key]
        if not isinstance(value, (list, dict)):
            continue
        try:
            blob = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        except (TypeError, ValueError):
            continue
        total_json += len(blob)
        n = len(value)
        print(f'  {key:<18} {len(blob) / 1048576:7.2f} MB   {n:>6} 项')
    print(f'  {"合计":<18} {total_json / 1048576:7.2f} MB')
    flights = plan.get('flights') or []
    if flights:
        one = json.dumps(flights[0], ensure_ascii=False, separators=(',', ':'))
        print(f'  单架次 {len(one)} B × {len(flights)} 架 = '
              f'{len(one) * len(flights) / 1048576:.2f} MB（flights 部分）')

    # 关键问题：这份 plan 常驻时的**真实**内存（RSS 口径）
    held = [plan]
    gc.collect()
    print(f'\n[常驻] 持有 1 份计划后 RSS   {rss_mb():8.1f} MB')

    # 模拟 JOBS=4：再建 3 份不同场景，看 4 份同时驻留要多少
    for i, (seed, scenario) in enumerate([(7, 'clear'), (13, 'fog'), (21, 'storm')], start=2):
        t0 = time.time()
        held.append(service.simulate(seed=seed, scenario=scenario, weather_mode='virtual'))
        gc.collect()
        print(f'[常驻] 第 {i} 份（seed={seed}, {scenario}） {time.time() - t0:5.1f}s '
              f'→ RSS {rss_mb():8.1f} MB')

    print(f'\n{"=" * 74}')
    print(f'结论：持有 {len(held)} 份计划的 RSS = {rss_mb():.1f} MB')
    print(f'      基线（import 后）= {base_rss:.1f} MB')
    print(f'      平均每份 ≈ {(rss_mb() - base_rss) / len(held):.1f} MB')
    print(f'{"=" * 74}')
    print('（Windows 与服务器 Linux 绝对数差 5–15%，单份成本可平移。）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
