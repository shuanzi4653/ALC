# -*- coding: utf-8 -*-
"""验证 cma_tiles 的时区修正：现在取到的时次应当是"刚刚"，不是 8 小时前。只读。

本探针通过 importlib 直接加载 cma_tiles.py（该模块无第三方依赖），
绕开 traffic 包的 __init__，因此不需要项目 venv。
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys

PATH = r"C:\Users\12921\Desktop\ALC\backend-python\traffic\cma_tiles.py"
spec = importlib.util.spec_from_file_location("cma_tiles_probe", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

now_utc = dt.datetime.now(dt.timezone.utc)
print(f"now(UTC)      = {now_utc:%Y-%m-%d %H:%M:%SZ}")
print(f"now(北京时)   = {now_utc.astimezone(mod.SLOT_TZ):%Y-%m-%d %H:%M}")

slot = mod.latest_slot()
print(f"latest_slot() = {slot:%Y-%m-%d %H:%M %z}  (北京时字面值)")
print(f"  -> tile_url = .../{slot:%Y%m%d}/{slot:%H}/{slot:%M}/3/3/6.bin")
print(f"  -> 绝对时刻  = {mod.slot_instant(slot):%Y-%m-%d %H:%M:%SZ}")

print("\n== 真实取帧（走网络） ==")
result = mod.frame(force=True)
print(f"  available        = {result.get('available')}")
print(f"  slot (UTC)       = {result.get('slot')}")
print(f"  slotLocal        = {result.get('slotLocal')}")
print(f"  slotAgeMinutes   = {result.get('slotAgeMinutes')}")
print(f"  lookbackSteps    = {result.get('lookbackStepsUsed')}")
print(f"  gridTiles        = {result.get('gridTiles')}")
st = result.get('stats') or {}
print(f"  stats            = present={st.get('present')} echo={st.get('echoFraction')} "
      f"conv={st.get('convectiveFraction')} strong={st.get('strongFraction')} "
      f"min={st.get('minDbz')} max={st.get('maxDbz')}")
if not result.get('available'):
    print(f"  error            = {result.get('error')}")

print("\n== 判据 ==")
age = result.get('slotAgeMinutes')
if age is None:
    print("  未能取到帧，无法判定时区修正的实际效果")
    sys.exit(2)
if age <= 60:
    print(f"  时次年龄 {age:.1f} 分钟 ⇒ **修正生效**（修正前会恒为约 480 分钟）")
elif age >= 400:
    print(f"  时次年龄 {age:.1f} 分钟 ⇒ **修正未生效，仍是 8 小时前的旧图**")
else:
    print(f"  时次年龄 {age:.1f} 分钟 ⇒ 介于两者之间，需人工确认")
