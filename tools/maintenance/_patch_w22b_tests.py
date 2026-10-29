# -*- coding: utf-8 -*-
"""W-22b：把高度文案的两条旧契约断言同步成新文案（0.11.4）。

旧断言钉的是 `<1 m`，而 `<1 m` 正是复测报告 P1-8 的那个症状：
地图上并排 `鸡西 ↔ 七台河 · <1 m`，读起来像"飞机贴地飞"。
新文案把它说成事实：在空却 <1 m 只可能是推演未推进 → `待起飞`；脏输入 → `高度未上报`。

同一次改动里必须改断言（M95）：改了实现留着旧字面量，下一个人会以为那是回归。
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'tests' / 'vehicleLabels.test.mjs'
text = PATH.read_text(encoding='utf-8')

old_block = """test('altitude display never writes 0 m for a vehicle the map calls airborne',()=>{
  // 过滤按状态（AIRBORNE），显示按高度：刚离地那一瞬间两者精度不同，四舍五入会写出
  // 「0 m」—— 一架"在飞"的飞机标着自己在地面。所以不足 1 m 一律写 `<1 m`。
  assert.equal(altitudeText(0),'<1 m')
  assert.equal(altitudeText(0.4),'<1 m')
  assert.equal(altitudeText(-3),'<1 m')
  assert.equal(altitudeText(1),'1 m')
  assert.equal(altitudeText(349.6),'350 m')
  // 脏输入不能变成 `NaN m` 印在地图上。
  assert.equal(altitudeText(null),'<1 m')
  assert.equal(altitudeText(undefined),'<1 m')
  assert.equal(altitudeText('abc'),'<1 m')
})"""

new_block = """test('altitude display never writes 0 m for a vehicle the map calls airborne',()=>{
  // 过滤按状态（AIRBORNE），显示按高度：刚离地那一瞬间两者精度不同，四舍五入会写出
  // 「0 m」—— 一架"在飞"的飞机标着自己在地面。
  //
  // 0.11.4（W-22b）：文案从 `<1 m` 改成 `待起飞`。原因不是嫌它不好看 ——
  // 复测报告 P1-8 的截图里地图上并排 `鸡西 ↔ 七台河 · <1 m`，评委的第一句是
  // "飞机为什么在 0 米高度飞"。挂标签的前提是本帧判为在空，而在空却 <1 m
  // 只可能是推演尚未推进（T+0 的轨迹点仍是地面高度）。说成事实即可。
  assert.equal(altitudeText(0),'待起飞')
  assert.equal(altitudeText(0.4),'待起飞')
  assert.equal(altitudeText(-3),'待起飞')
  assert.equal(altitudeText(1),'1 m')
  assert.equal(altitudeText(349.6),'350 m')
  // 脏输入不能变成 `NaN m` 印在地图上；也不能说成"待起飞"（那是另一个事实）。
  assert.equal(altitudeText(null),'高度未上报')
  assert.equal(altitudeText(undefined),'高度未上报')
  assert.equal(altitudeText('abc'),'高度未上报')
})"""
if old_block not in text:
    raise SystemExit('高度断言块不存在')
text = text.replace(old_block, new_block, 1)

old2 = "  assert.equal(vehicleLabel({name:'牡丹江 · 牡丹江收货节点2'},0),'牡丹江收货节点2 · <1 m')"
new2 = ("  // 0.11.4（W-22b）：0 高度不再印 `<1 m`（读起来像贴地飞），改说 `待起飞`；\n"
        "  // 判据同时钉住『地图上不会出现 <1 m』这件事本身。\n"
        "  assert.equal(vehicleLabel({name:'牡丹江 · 牡丹江收货节点2'},0),'牡丹江收货节点2 · 待起飞')\n"
        "  assert.doesNotMatch(vehicleLabel({name:'鸡西 ↔ 七台河'},0),/<1 m/)")
if old2 not in text:
    raise SystemExit('vehicleLabel 断言不存在')
text = text.replace(old2, new2, 1)

PATH.write_text(text, encoding='utf-8')
print('vehicleLabels.test.mjs patched')
