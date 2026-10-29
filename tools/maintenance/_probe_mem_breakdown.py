"""量 AIC-Python 的内存构成：雷达帧缓存、活计划、模块基线。

只读探针，不改任何东西。目标是回答"480 MB 里哪一块可以被削减"。

用法（cwd = backend-python）：
    ./.venv/Scripts/python.exe ../tools/maintenance/_probe_mem_breakdown.py
"""
from __future__ import annotations

import gc
import json
import os
import sys
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '/backend-python')


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
    fn.argtypes[0] = wintypes.HANDLE
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    if not fn(handle, ctypes.byref(pmc), pmc.cb):
        return -1.0
    return pmc.WorkingSetSize / 1048576


def deep_size(obj, seen=None, depth=0, maxdepth=6):
    """递归估算 Python 对象的实际体量（含 numpy 的 nbytes）。"""
    if seen is None:
        seen = set()
    oid = id(obj)
    if oid in seen or depth > maxdepth:
        return 0
    seen.add(oid)
    size = sys.getsizeof(obj, 0)
    nbytes = getattr(obj, 'nbytes', None)
    if isinstance(nbytes, int) and nbytes > 0:
        size += nbytes  # numpy 数组/内存视图
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:2000]:
            size += deep_size(k, seen, depth + 1, maxdepth) + deep_size(v, seen, depth + 1, maxdepth)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for v in list(obj)[:2000]:
            size += deep_size(v, seen, depth + 1, maxdepth)
    return size


def mb(n: float) -> str:
    return f'{n / 1048576:.1f} MB'


def main() -> int:
    print('=' * 72)
    print('AIC-Python 内存构成探针')
    print('=' * 72)
    base = rss_mb()
    print(f'[0] 空解释器 RSS            {base:8.1f} MB')

    from datetime import timedelta

    from traffic import service, v2
    print(f'[1] import traffic.* 后 RSS  {rss_mb():8.1f} MB   (+{rss_mb() - base:.1f})')

    # ---- 2) 单帧虚拟雷达的体积：这是 _virtual_radar_derived 的缓存单元 ----
    before = rss_mb()
    base_time = service.SIMULATION_BASE_TIME
    frame = service._virtual_radar_derived(42, base_time)
    after = rss_mb()
    print(f'\n[2] 单帧 _virtual_radar_derived(42, 0)')
    print(f'    构建 RSS 增量           {after - before:8.1f} MB')
    print(f'    帧对象类型              {type(frame).__name__}')
    keys = list(frame.keys()) if isinstance(frame, dict) else []
    print(f'    帧的键                  {keys}')
    frame_size = deep_size(frame, maxdepth=3)
    print(f'    深度估算体量            {mb(frame_size)}')
    if isinstance(frame, dict):
        for k, v in frame.items():
            n = getattr(v, 'nbytes', None)
            print(f'      - {k:<14} {type(v).__name__:<12} '
                  f'{"nbytes=" + mb(n) if isinstance(n, int) else "size=" + mb(sys.getsizeof(v, 0))}')

    # ---- 3) 缓存填满 16 帧后能涨多少 ----
    print(f'\n[3] 缓存 16 帧的稳态增量（实测填到 16）')
    before = rss_mb()
    for i in range(1, 16):
        service._virtual_radar_derived(42, base_time + timedelta(minutes=6 * i))
    gc.collect()
    after = rss_mb()
    print(f'    填满 16 帧 RSS 增量     {after - before:8.1f} MB')
    info = service._virtual_radar_derived.cache_info()
    print(f'    cache_info              {info}')

    # ---- 4) 活计划（session）的体量 ----
    print(f'\n[4] 一次计划构建的稳态体量')
    before = rss_mb()
    session = service.session(42, 'clear')
    gc.collect()
    after = rss_mb()
    print(f'    service.session RSS 增量 {after - before:8.1f} MB')
    print(f'    plan 体量（深度估算）   {mb(deep_size(session, maxdepth=4))}')
    for key in ('flights', 'mapFlights', 'routes', 'hubs', 'corridors'):
        rows = session.get(key) if isinstance(session, dict) else None
        if isinstance(rows, list):
            print(f'      - {key:<12} {len(rows):>6} 条   {mb(deep_size(rows, maxdepth=3))}')

    # ---- 5) 各模块级缓存的当前规模 ----
    print(f'\n[5] 模块级缓存规模')
    print(f'    _RADAR_WINDOW_CACHE     {len(getattr(service, "_RADAR_WINDOW_CACHE", {}))} 项')
    print(f'    _RADAR_ERODED_CACHE     {len(getattr(service, "_RADAR_ERODED_CACHE", {}))} 项')
    print(f'    lru_cache 清单：')
    for name in dir(service):
        fn = getattr(service, name, None)
        if hasattr(fn, 'cache_info') and callable(fn.cache_info):
            try:
                print(f'      - {name:<34} {fn.cache_info()}')
            except Exception:
                pass

    print(f'\n[6] 最终 RSS                {rss_mb():8.1f} MB')
    print('\n（本机是 Windows，服务器是 Linux；两者绝对数会差 5–15%，但各块的相对占比可比。）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
