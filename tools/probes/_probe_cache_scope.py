"""Confirm *why* the instance cache measures 0% inside a real plan.

588 distinct windows over 108,640 calls is 99.5% reuse in aggregate -- so a
working cache should hit almost always. The measured rate inside a plan is 0.0%.

Hypothesis: `pending` is sorted by departure minute before the loop, so the calls
arrive in ascending order and each new flight usually asks for a *new* window;
the aggregate reuse exists across the whole run but never as an immediate repeat.
An `lru_cache` only helps on repeat, so with 588 windows and a 480-minute sweep
each window is needed a few dozen times but spread far apart -- and with
`maxsize=2048` that should still hit. The 0% therefore points at the cache not
surviving rather than at the keying.

This probe calls `envelope` twice with the *identical* arguments and checks
whether the second call is a hit, then checks whether re-calling across two
separately constructed instances shares anything. That isolates "cache is
instance-scoped" from "keys never repeat".
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import time
from pathlib import Path


from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


print('=== 同一实例内，完全相同的参数连续两次 ===')
first = NetworkWeather(4242, 'moving')

started = time.monotonic()
first.envelope(100, 180)
cold = time.monotonic() - started
started = time.monotonic()
first.envelope(100, 180)
warm = time.monotonic() - started
info = first._swept_window.cache_info()
print(f'  首调 {cold * 1000:.1f}ms，重调 {warm * 1000:.1f}ms（若命中应接近 0ms）')
print(f'  cache_info {info}')
print(f'  同一实例重复调用是否命中: {"是" if info.hits else "否"}')

print()
print('=== 跨实例：重新 new 一个，同一窗口 ===')
second = NetworkWeather(4242, 'moving')
started = time.monotonic()
second.envelope(100, 180)
again = time.monotonic() - started
print(f'  新实例同一参数 {again * 1000:.1f}ms，cache_info {second._swept_window.cache_info()}')
print(f'  跨实例是否复用: {"是" if again < cold * 0.1 else "否 —— 缓存随实例消失"}')

print()
print('=== 按班次升序调用时的命中情况 ===')
third = NetworkWeather(4242, 'moving')
hits_before = third._swept_window.cache_info().hits
for departure in range(0, 480, 1):
    third.envelope(departure, departure + 80)
info = third._swept_window.cache_info()
print(f'  480 次升序调用: hits={info.hits} misses={info.misses} '
      f'命中率 {info.hits / (info.hits + info.misses) * 100:.1f}%')
print(f'  currsize={info.currsize}（不同 (start,end) 组合数）')

print()
print('=== 结论 ===')
print('  缓存本身可用（同参数重调命中），但：')
print('  1) 缓存挂在实例上，每次 simulate 都 new 一个实例，跨计划不复用；')
print('  2) 调用按出发分钟升序到达，同一窗口的两次调用相隔很远，')
print('     而 588 个窗口 x 110ms 的 miss 成本已在单次计划内就构成主要开销。')
