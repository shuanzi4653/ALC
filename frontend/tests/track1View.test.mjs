import test from 'node:test'
import assert from 'node:assert/strict'
import {buildTrack1View, track1SnapshotOf, TRACK1_DECISIONS} from '../src/traffic/runtime.js'

// 轨1 研判卡（0.10.1（Beta））的判据。
//
// 这里钉的**不是**"模型准不准"（那个问题在成效页，且带分母），而是一条红线：
// **模型不能把结论变得更乐观**。规则说禁飞、模型说适飞 ⇒ 仍然是禁飞。
// 这条红线的危险在于，它最"合理"的破坏方式恰恰看起来更科学：
// 把两条路径按置信度加权。加权意味着一个 99% 置信的模型可以把 BAN 稀释成 DANGER，
// 而界面上那个数字会更漂亮、曲线会更平滑 —— 所以必须有一条判据在它变红时喊出来。

const rule = (level, sfi = 50, extra = {}) => ({
  level, sfi, levelLabel: level, ruleVersion: 'v1', reasons: ['测试用规则结果'], ...extra,
})

const model = (level, extra = {}) => ({
  available: true, status: 'OK', level, levelLabel: level, confidence: 0.9, margin: 0.8,
  lowConfidence: false, probabilities: {}, top3: [{feature: 'windSpeed', value: 9.4, score: 0.3}],
  missingFeatures: [], degraded: {flag: false, reason: null},
  modelVersion: 'ml-v1', labelsVersion: 'v1', decidedBy: 'MODEL', ...extra,
})

test('模型更乐观：规则否决，档位不变（置信度再高也不翻案）', () => {
  const view = buildTrack1View({rule: rule('BAN', 30), model: model('FIT', {confidence: 0.99})})
  assert.equal(view.decision, 'RULE_OVERRIDES_MODEL')
  assert.equal(view.finalLevel, 'BAN')
  assert.equal(view.finalLabel, '禁飞')
  // 置信度照常透传 —— 它不是被吞掉，而是**不参与定档**。
  assert.equal(view.model.confidence, 0.99)
})

test('模型更乐观：跨两档（BAN → CAUTION）同样不降', () => {
  const view = buildTrack1View({rule: rule('BAN', 25), model: model('CAUTION')})
  assert.equal(view.decision, 'RULE_OVERRIDES_MODEL')
  assert.equal(view.finalLevel, 'BAN')
})

test('模型更保守：采纳模型档（只升不降）', () => {
  const view = buildTrack1View({rule: rule('CAUTION', 70), model: model('BAN')})
  assert.equal(view.decision, 'MODEL_STICTER')
  assert.equal(view.finalLevel, 'BAN')
})

test('同档：记为一致，但措辞不许说成"互相验证"', () => {
  const view = buildTrack1View({rule: rule('DANGER', 40), model: model('DANGER')})
  assert.equal(view.decision, 'CONSISTENT')
  assert.equal(view.finalLevel, 'DANGER')
  // 模型的标签本来就来自一份判据，所以"一致"不是独立印证。
  assert.match(TRACK1_DECISIONS.CONSISTENT.note, /不是"互相验证"/)
})

test('模型缺席：显示"未参与"，且绝不显示成一个档位', () => {
  const view = buildTrack1View({rule: rule('DANGER', 40), model: {available: false, status: 'MODEL_NOT_FOUND'}})
  assert.equal(view.decision, 'MODEL_UNAVAILABLE')
  assert.equal(view.finalLevel, 'DANGER')
  // 关键：不是 'FIT'，也不是 'DANGER' —— 而是 null + 一句为什么。
  assert.equal(view.model.level, null)
  assert.equal(view.model.levelLabel, null)
  assert.equal(view.model.absentReason, 'MODEL_NOT_FOUND')
  // 没参与就不该印归因说明（印了会把缺席讲成有结论）。
  assert.equal(view.attributionNote, null)
})

test('还没请求：与"没有模型"分开，但同样算未参与', () => {
  const view = buildTrack1View({rule: rule('FIT', 95), model: null})
  assert.equal(view.decision, 'MODEL_UNAVAILABLE')
  assert.equal(view.model.requested, false)
  assert.equal(view.model.absentReason, 'NOT_REQUESTED')
  assert.equal(view.finalLevel, 'FIT')
})

test('置信度 0 与"没有置信度"必须分得开', () => {
  const zero = buildTrack1View({rule: rule('FIT', 95), model: model('FIT', {confidence: 0})})
  assert.equal(zero.model.confidence, 0)
  const absent = buildTrack1View({rule: rule('FIT', 95), model: model('FIT', {confidence: null})})
  assert.equal(absent.model.confidence, null)
  const missing = buildTrack1View({rule: rule('FIT', 95), model: model('FIT', {confidence: undefined})})
  assert.equal(missing.model.confidence, null)
})

test('非法档位不被默认成 FIT', () => {
  const view = buildTrack1View({rule: rule('FLY', 88), model: model('FIT')})
  // 规则档位不合法 ⇒ 没有规则结论 ⇒ 不给结论，而不是拿模型的 FIT 顶上。
  assert.equal(view.rule.level, null)
  assert.equal(view.decision, 'UNKNOWN')
  assert.equal(view.finalLevel, null)
})

test('模型缺测与低置信照常透传，供界面降级提示', () => {
  const view = buildTrack1View({
    rule: rule('CAUTION', 65),
    model: model('CAUTION', {
      lowConfidence: true, margin: 0.02,
      missingFeatures: ['windGust', 'precipMmh', 'visibilityM'],
      degraded: {flag: true, reason: '关键要素缺测 3 个（windGust、precipMmh、visibilityM），档位基于训练中位数填充'},
    }),
  })
  assert.equal(view.model.lowConfidence, true)
  assert.equal(view.model.margin, 0.02)
  assert.equal(view.model.degraded, true)
  assert.match(view.model.degradedReason, /中位数填充/)
  assert.equal(view.model.missingFeatures.length, 3)
})

test('四态全列（只画当前那一种，读者无从知道还有另外三种）', () => {
  const view = buildTrack1View({rule: rule('FIT', 95), model: model('FIT')})
  assert.deepEqual(view.decisions.map(d => d.key),
    ['CONSISTENT', 'MODEL_STICTER', 'RULE_OVERRIDES_MODEL', 'MODEL_UNAVAILABLE'])
})

test('Top3 特征带中文名，未知特征保留原名而不是丢掉', () => {
  const view = buildTrack1View({
    rule: rule('FIT', 95),
    model: model('FIT', {top3: [
      {feature: 'windSpeed', value: 9.4, score: 0.3},
      {feature: 'newFeature', value: 1, score: 0.1},
    ]}),
  })
  assert.equal(view.model.top3[0].featureLabel, '平均风速')
  // 未登记的特征：显示原名。丢条目会让"三个因子"悄悄变成两个。
  assert.equal(view.model.top3[1].featureLabel, 'newFeature')
  assert.equal(view.model.top3.length, 2)
})

test('怪输入不抛异常（这一屏在首屏路径上）', () => {
  for (const bad of [undefined, null, 0, '', [], 'x', {}, {rule: 7, model: 'y'}]) {
    const view = buildTrack1View(bad)
    assert.equal(typeof view.decision, 'string')
    assert.equal(typeof view.decisionLabel, 'string')
    assert.ok(view.decisions.length > 0)
    assert.equal(typeof view.model.available, 'boolean')
  }
})

// ---- 观测条目 → 请求体 -----------------------------------------------------
// 归一化本身是"静默出错"的高发地：字段名认错了不会报错，只会让模型按中位数
// 猜一个档位，而界面上那个档位看起来完全正常。

test('四个别名都要认：三套来源各用各的键名', () => {
  const openMeteo = track1SnapshotOf({
    cityId: 'SHE', windSpeed10mMps: 7.2, windGusts10mMps: 12.4,
    precipitationMm: 0.3, visibilityM: 9000, temperatureC: 18.2, humidity: 0.62,
    cloudCover: 0.4, pressureMslHpa: 1009, validAt: '2026-10-17T02:00:00Z',
  })
  assert.equal(openMeteo.snapshot.windSpeed, 7.2)
  assert.equal(openMeteo.snapshot.windGust, 12.4)
  assert.equal(openMeteo.snapshot.precipMmh, 0.3)
  assert.equal(openMeteo.snapshot.visibilityM, 9000)
  assert.equal(openMeteo.snapshot.tempC, 18.2)
  assert.equal(openMeteo.snapshot.pressureHpa, 1009)

  const alt = track1SnapshotOf({cityId: 'DLC', windMps: 4, gustMps: 9, tempC: 3})
  assert.equal(alt.snapshot.windSpeed, 4)
  assert.equal(alt.snapshot.windGust, 9)
  assert.equal(alt.snapshot.tempC, 3)
})

test('缺测给 null，不许填 0（填 0 等于替天气做了一次有利的伪证）', () => {
  const thin = track1SnapshotOf({cityId: 'SHE', tempC: 12})
  assert.equal(thin.snapshot.windSpeed, null)
  assert.notEqual(thin.snapshot.windSpeed, 0)
  assert.equal(thin.snapshot.visibilityM, null)
  assert.equal(thin.complete, false)
  assert.ok(thin.present.length < Object.keys(thin.snapshot).length)
})

test('能见度走 hourly 首非空（这是既有的唯一取值路径，不许在这里另写一套）', () => {
  const view = track1SnapshotOf({cityId: 'SHE', hourly: {visibility: [null, 3200, 4000]}})
  assert.equal(view.snapshot.visibilityM, 3200)
})

test('sampleKey 与训练样本同一套命名（便于线上样本回查训练集）', () => {
  const view = track1SnapshotOf({cityId: 'SHE', validAt: '2026-07-06T04:00:00Z'})
  assert.equal(view.sampleKey, 'SHE-2026-07-06T0400')
  assert.equal(track1SnapshotOf({cityId: 'SHE'}).sampleKey, null)
  assert.equal(track1SnapshotOf({cityId: 'SHE', validAt: 'not-a-date'}).sampleKey, null)
})

test('空观测不抛异常，只是"什么都没拿到"', () => {
  for (const bad of [undefined, null, 0, '', [], 'x']) {
    const view = track1SnapshotOf(bad)
    assert.equal(view.present.length, 0)
    assert.equal(view.complete, false)
    assert.equal(view.cityId, null)
  }
})
