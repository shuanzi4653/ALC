import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {dirname, join} from 'node:path'
import {buildMlEffectView, ML_EFFECT_SNAPSHOT} from '../src/traffic/runtime.js'

// 成效页三列（0.10.1（Beta））的判据。
//
// 两件事在这里守：
//   1. **"没有数字"与"数字是 0"必须长得不一样**。人工仲裁那一列还没填完，
//      macroF1 是 null；渲染成 0.000 会被读成"人工判断一团糟"。
//   2. **页面上的数与训练产物必须是同一个数**。页面上印 0.977、报告里写 0.98，
//      谁也没错，读者却没法判断哪个是真的。下面第三条用例直接读
//      `data/training/model-v1-metrics.json` 比对 —— 训练结果一换，这条就红。

const HERE = dirname(fileURLToPath(import.meta.url))
const METRICS = join(HERE, '..', '..', 'data', 'training', 'model-v1-metrics.json')

test('三列齐全，人工仲裁未填完时给 — 而不是 0.000', () => {
  const view = buildMlEffectView()
  assert.equal(view.empty, false)
  assert.deepEqual(view.rows.map(r => r.key), ['rule', 'model', 'manual'])

  const manual = view.rows.find(r => r.key === 'manual')
  assert.equal(manual.macroF1, null)
  assert.equal(manual.macroF1Text, '—')
  assert.equal(manual.measured, false)
  // 分母是有的（42 条仲裁表），只是结果还没填 —— 两件事不能混为一谈。
  assert.equal(manual.denominator, 42)
})

test('危险漏报同时给绝对值与分母（2/99 与 2/9 不该长得一样）', () => {
  const view = buildMlEffectView()
  const model = view.rows.find(r => r.key === 'model')
  assert.equal(model.dangerMiss, 2)
  assert.equal(model.dangerHit, 97)
  assert.equal(model.dangerMissText, '2/99')
  assert.equal(model.dangerRecall, 0.9798)
})

test('页面快照与训练产物逐项一致（不许手抄一个更好看的数）', () => {
  const raw = JSON.parse(readFileSync(METRICS, 'utf8'))
  const metrics = raw.metrics
  const rf = metrics.RandomForest
  const rule = metrics.RuleBaseline

  assert.equal(ML_EFFECT_SNAPSHOT.source, 'data/training/model-v1-metrics.json')
  assert.equal(ML_EFFECT_SNAPSHOT.samples, raw.samples)
  assert.equal(ML_EFFECT_SNAPSHOT.testSize, raw.testSize)
  assert.equal(ML_EFFECT_SNAPSHOT.parity.includes(String(raw.parityTested)), true)

  const view = buildMlEffectView()
  const modelRow = view.rows.find(r => r.key === 'model')
  assert.equal(modelRow.macroF1, rf.macroF1)
  assert.equal(modelRow.accuracy, rf.accuracy)
  assert.equal(modelRow.dangerMiss, rf.dangerMiss)
  assert.equal(modelRow.dangerHit, rf.dangerHit)

  const ruleRow = view.rows.find(r => r.key === 'rule')
  assert.equal(ruleRow.macroF1, rule.macroF1)
  assert.equal(ruleRow.accuracy, rule.accuracy)
  assert.equal(ruleRow.dangerMiss, rule.dangerMiss)
  assert.equal(ruleRow.dangerHit, rule.dangerHit)
})

test('标注一致性：κ 读自一致性报告，不在这里另算一个', () => {
  const raw = JSON.parse(readFileSync(join(HERE, '..', '..', 'data', 'training',
    'label-agreement.json'), 'utf8'))
  const view = buildMlEffectView()
  assert.equal(view.annotation.weightedKappa, raw.agreement.weightedKappa)
  assert.equal(view.annotation.raw, raw.agreement.raw)
  assert.equal(view.annotation.count, raw.agreement.n)
})

test('最高分那一列的说明不许升格成"模型最准"', () => {
  const view = buildMlEffectView()
  assert.equal(view.best, 'model')
  // 只说"最贴近判据"。说成"最贴近天气"就是另一件事，而仓库里没有观测真值。
  // 0.11.1（Beta）换芯后这两句口径必须改（M95：改设计同一次改判据）。
  // 原判据钉的是"最贴近判据 / 不是预测天气的能力"——它同时是**对的话**和**自伤的话**：
  // 手册 §6 把它列为全站最贵的一句。现在钉的是"新旧两套不可并列 + 指向模型卡"。
  assert.match(view.bestNote, /判据复现口径/)
  assert.match(view.bestNote, /模型卡/)
  assert.match(view.caveat, /不代表 0.11\.1 的预测能力/)
  assert.match(view.caveat, /不可并列比较/)
  assert.doesNotMatch(view.caveat, /不是「预测天气的能力」/, '旧口径不许留在文案里')
})

test('分母为 0 时危险召回率给 null，不给 0', () => {
  const view = buildMlEffectView({
    columns: [{key: 'x', label: 'X', macroF1: null, dangerMiss: null, dangerHit: null, denominator: 0}],
  })
  assert.equal(view.rows[0].dangerRecall, null)
  assert.equal(view.rows[0].macroF1Text, '—')
})

test('空列给 empty 标记，并说明"还没有结论"而不是"表现很差"', () => {
  const view = buildMlEffectView({columns: []})
  assert.equal(view.empty, true)
  assert.deepEqual(view.rows, [])
  assert.equal(view.best, null)
  assert.match(view.bestNote, /还没有可比的 macroF1/)
})

test('怪输入不抛异常', () => {
  for (const bad of [undefined, null, 0, '', [], 'x', {}, {columns: 'nope'}]) {
    const view = buildMlEffectView(bad)
    assert.equal(typeof view.empty, 'boolean')
    assert.ok(Array.isArray(view.rows))
    assert.equal(typeof view.caveat, 'string')
  }
})
