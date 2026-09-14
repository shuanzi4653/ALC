import test from 'node:test'
import assert from 'node:assert/strict'
import {
  LEVEL_STYLES, LEVEL_COLORS, LEVEL_LABELS, UNKNOWN_STYLE,
  levelStyle, levelColor, levelLabel, isRiskLevel
} from '../src/utils.js'

test('四级颜色互不相同（谨慎不得与适飞共用绿色）', () => {
  const colors = Object.values(LEVEL_STYLES).map(s => s.color)
  assert.equal(new Set(colors).size, colors.length, '存在重复颜色')
  assert.notEqual(LEVEL_STYLES.CAUTION.color, LEVEL_STYLES.FIT.color)
  assert.notEqual(LEVEL_STYLES.DANGER.color, LEVEL_STYLES.BAN.color)
})

test('「禁入」措辞只属于禁飞等级', () => {
  assert.match(LEVEL_STYLES.BAN.areaLabel, /禁入/)
  assert.doesNotMatch(LEVEL_STYLES.DANGER.areaLabel, /禁入/)
  assert.doesNotMatch(LEVEL_STYLES.CAUTION.areaLabel, /禁入/)
  assert.doesNotMatch(LEVEL_STYLES.FIT.areaLabel, /禁入/)
})

test('未知等级为灰色不可判定，不冒充适飞', () => {
  for (const value of [null, undefined, '', 'UNDETERMINED', 'UNKNOWN']) {
    assert.equal(levelColor(value), UNKNOWN_STYLE.color)
    assert.equal(levelLabel(value), UNKNOWN_STYLE.label)
    assert.notEqual(levelStyle(value).color, LEVEL_STYLES.FIT.color)
  }
})

test('旧导出与统一样式表保持一致', () => {
  for (const key of Object.keys(LEVEL_STYLES)) {
    assert.equal(LEVEL_COLORS[key], LEVEL_STYLES[key].color)
    assert.equal(LEVEL_LABELS[key], LEVEL_STYLES[key].label)
  }
})

test('风险区判定仅覆盖危险与禁飞', () => {
  assert.equal(isRiskLevel('DANGER'), true)
  assert.equal(isRiskLevel('BAN'), true)
  assert.equal(isRiskLevel('CAUTION'), false)
  assert.equal(isRiskLevel('FIT'), false)
  assert.equal(isRiskLevel(null), false)
})
