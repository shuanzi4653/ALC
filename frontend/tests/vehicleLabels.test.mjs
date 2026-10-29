import test from 'node:test'
import assert from 'node:assert/strict'
import {vehicleLabelText,vehicleLabel,altitudeText,labelWidth,selectVehicleLabels} from '../src/traffic/runtime.js'

// 用户 2026-10-03：「为什么不是所有的都有标签？」—— 地图上每一架在空载具都要有标签。
// 但"都挂上"和"都能读"是两件事：上百个标签无脑铺开会叠成一团，那与没有标签是同一个
// 结果。所以这里钉的是两件事：**文字怎么拼**（纯字符串）与**留下的怎么选**（版面抑制）。
// 这两条都不可能在浏览器里被测到 —— 组件私有函数对 `node --test` 不可见，所以判据
// 必须住在 runtime.js 的纯函数里。

test('labels shorten the repeated delivery city prefix and leave city pairs alone',()=>{
  // 配送班次的名字是「城市 · 城市节点N」：前缀与后半段的城市名重复了一遍。
  assert.equal(vehicleLabelText({name:'牡丹江 · 牡丹江收货节点2'}),'牡丹江收货节点2')
  assert.equal(vehicleLabelText({name:'大连 · 大连商家节点4'}),'大连商家节点4')
  // 城际班次的名字不含 ` · `，必须原样返回 —— 砍掉它就是砍掉一半信息。
  assert.equal(vehicleLabelText({name:'沈阳 ↔ 本溪'}),'沈阳 ↔ 本溪')
  // 前缀**不是**后半段的前缀时不许乱砍：那说明两个名字真的不同。
  assert.equal(vehicleLabelText({name:'A · B节点'}),'A · B节点')
  // 没有 name 时退回 id，两者都没有时返回空串（宁可空标签也不要 "undefined"）。
  assert.equal(vehicleLabelText({id:'CAR-1-01-1-05-0-0'}),'CAR-1-01-1-05-0-0')
  assert.equal(vehicleLabelText({}),'')
  assert.equal(vehicleLabelText(null),'')
})

test('altitude display never writes 0 m for a vehicle the map calls airborne',()=>{
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
})

test('a vehicle label is the name plus the shared altitude wording',()=>{
  assert.equal(vehicleLabel({name:'哈尔滨 ↔ 大庆'},350),'哈尔滨 ↔ 大庆 · 350 m')
  // 0.11.4（W-22b）：0 高度不再印 `<1 m`（读起来像贴地飞），改说 `待起飞`；
  // 判据同时钉住『地图上不会出现 <1 m』这件事本身。
  assert.equal(vehicleLabel({name:'牡丹江 · 牡丹江收货节点2'},0),'牡丹江收货节点2 · 待起飞')
  assert.doesNotMatch(vehicleLabel({name:'鸡西 ↔ 七台河'},0),/<1 m/)
  // 没有身份就没有标签：一枚只有高度的标签比没有标签更糟（它不说明任何事）。
  assert.equal(vehicleLabel({},120),'')
  assert.equal(vehicleLabel(null,120),'')
})

test('label width counts full-width characters wider than half-width ones',()=>{
  // 全角按 10.4、半角按 5.8、末尾 14 的内边距：中文标签必须被算得比同长度的英文宽，
  // 否则抑制器会以为两个标签还隔得开，实际已经叠上了。
  const cn=labelWidth('沈阳 ↔ 本溪'),en=labelWidth('SHENYANG')
  assert.ok(cn>en,'a 6-glyph Chinese label must measure wider than 8 Latin letters')
  // 单调性：加字符一定变宽（抑制器的排序依赖它不能反着动）。
  assert.ok(labelWidth('abc')<labelWidth('abcd'))
  assert.equal(labelWidth(''),14)
  assert.equal(labelWidth(null),14)
})

test('overlapping vehicle labels are suppressed but distant ones are all kept',()=>{
  const at=(id,x,y,extra={})=>({id,x,y,text:'沈阳 ↔ 本溪',width:80,...extra})
  // 负向对照：互不相干的三个候选**必须一个不少**地留下。没有这一条，
  // "抑制了重叠"与"抑制了一切"在断言里长得一模一样。
  assert.deepEqual(
    selectVehicleLabels([at('a',0,0),at('b',200,0),at('c',0,200)]).map(r=>r.id),
    ['a','b','c'])
  // 同一位置放两个：只留一个，另一个被压掉。
  const stacked=selectVehicleLabels([at('a',0,0),at('b',0,0)])
  assert.equal(stacked.length,1)
  // y 相距 40 px（标签自身高 16、悬在点位上方 22）不相交，两个都留。
  assert.equal(selectVehicleLabels([at('a',0,0),at('b',0,40)]).length,2)
})

test('label suppression prefers alerts, then the nearer vehicle, and is order-independent',()=>{
  const at=(id,x,y,extra={})=>({id,x,y,text:'沈阳 ↔ 本溪',width:80,...extra})
  // 告警优先：主控区/雷达内核越界的载具，标签必须活下来。
  assert.equal(selectVehicleLabels([at('plain',0,0),at('hot',0,0,{priority:1,bad:true})])[0].id,'hot')
  // 同级看远近：深度小（更靠近相机）的留下。
  assert.equal(selectVehicleLabels([at('far',0,0,{depth:9}),at('near',0,0,{depth:1})])[0].id,'near')
  // 完全同级时按 id 稳定排序 —— 同一帧重算不能改变留下的那一批，否则标签会闪。
  const rows=[at('c',0,0),at('a',0,0),at('b',0,0)]
  assert.equal(selectVehicleLabels(rows)[0].id,'a')
  assert.equal(selectVehicleLabels(rows.slice().reverse())[0].id,'a')
  // 上限是硬约束：铺不满也绝不能超。
  const many=[0,1,2,3,4].map(i=>at('n'+i,i*400,0))
  assert.equal(selectVehicleLabels(many,{max:2}).length,2)
  // 空输入与脏输入降级为空，不抛。
  assert.deepEqual(selectVehicleLabels([]),[])
  assert.deepEqual(selectVehicleLabels(null),[])
  assert.deepEqual(selectVehicleLabels([null,undefined]),[])
})
