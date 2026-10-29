import test from 'node:test'
import assert from 'node:assert/strict'
import {
  WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL,
  normalizeWeatherMode, weatherModeButtonState, weatherModeHints, weatherModeIsVirtual,
  weatherModeLabel, weatherModeNames, weatherModeStatusText,
} from '../src/traffic/runtime.js'

// The switch is the only way an operator changes the weather channel, and the
// wording is load-bearing: a button that says 虚拟气象 while the map still draws
// measured echoes is worse than no button. These tests pin the parts a .vue file
// cannot be tested for -- which button is clickable, and what the caption claims.

test('an absent or unknown mode resolves to measured', () => {
  // Matches the backend default and radarIsVirtual's "an unlabelled payload is a
  // measurement" rule: defaulting the other way would hide a real hazard behind
  // a "demo" label.
  for (const value of [undefined, null, '', 'MEASURED', 'virtual ', 0, {}, 'nonsense']) {
    assert.equal(normalizeWeatherMode(value), WEATHER_MODE_MEASURED, String(value))
  }
})

test('only the exact virtual string selects virtual', () => {
  assert.equal(normalizeWeatherMode(WEATHER_MODE_VIRTUAL), WEATHER_MODE_VIRTUAL)
  assert.equal(normalizeWeatherMode('virtual'), WEATHER_MODE_VIRTUAL)
  assert.equal(weatherModeIsVirtual('virtual'), true)
  assert.equal(weatherModeIsVirtual('measured'), false)
})

test('both modes have a label and a hint that names the source', () => {
  assert.deepEqual(Object.keys(weatherModeNames).sort(), ['measured', 'virtual'])
  // The hint is what tells the operator where the frame comes from before the
  // click, so it must not be interchangeable between the two modes.
  assert.notEqual(weatherModeHints[WEATHER_MODE_MEASURED], weatherModeHints[WEATHER_MODE_VIRTUAL])
  assert.match(weatherModeHints[WEATHER_MODE_VIRTUAL], /生成/)
  assert.match(weatherModeHints[WEATHER_MODE_MEASURED], /实测/)
})

test('the active button is marked active and cannot be re-clicked', () => {
  const measured = weatherModeButtonState(WEATHER_MODE_MEASURED, WEATHER_MODE_MEASURED)
  assert.equal(measured.active, true)
  assert.equal(measured.disabled, true, 'clicking the current mode would POST a no-op')
  assert.equal(measured.label, '实测气象')

  const other = weatherModeButtonState(WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL)
  assert.equal(other.active, false)
  assert.equal(other.disabled, false, 'the other mode must stay clickable')
  assert.equal(other.label, '虚拟气象')
})

test('an in-flight switch disables both buttons', () => {
  // Two overlapping POSTs could land out of order and leave the UI showing the
  // loser. Disabling both is what makes the button state trustworthy.
  for (const target of [WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL]) {
    const state = weatherModeButtonState(WEATHER_MODE_MEASURED, target, true)
    assert.equal(state.disabled, true, target)
  }
})

test('the button state is symmetric between the two modes', () => {
  const a = weatherModeButtonState(WEATHER_MODE_VIRTUAL, WEATHER_MODE_VIRTUAL)
  assert.equal(a.active, true)
  assert.equal(weatherModeButtonState(WEATHER_MODE_VIRTUAL, WEATHER_MODE_MEASURED).disabled, false)
})

test('virtual status text says the frame is not an observation', () => {
  const text = weatherModeStatusText(WEATHER_MODE_VIRTUAL, { framesServed: { virtualFrames: 7 } })
  assert.match(text, /虚拟/)
  assert.match(text, /不是观测数据/)
  assert.match(text, /7/)
})

test('virtual status text still refuses to call it an observation with no frames yet', () => {
  const text = weatherModeStatusText(WEATHER_MODE_VIRTUAL, { framesServed: {} })
  assert.match(text, /不是观测数据/)
  assert.doesNotMatch(text, /\d+ 帧/)
})

test('measured status text names the public source', () => {
  const text = weatherModeStatusText(WEATHER_MODE_MEASURED, { framesServed: { measuredFrames: 12 } })
  assert.match(text, /实测/)
  assert.match(text, /12/)
  assert.match(text, /公开/)
})

test('measured mode reports a dead source instead of claiming 实测', () => {
  // Saying "实测气象" while the upstream is down is the same lie in the other
  // direction, so the unavailable flag has to reach the text.
  const text = weatherModeStatusText(WEATHER_MODE_MEASURED, { available: false, framesServed: { measuredFrames: 3 } })
  assert.match(text, /不可用/)
})

test('an absent status object does not throw', () => {
  for (const mode of [WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL, undefined]) {
    assert.equal(typeof weatherModeStatusText(mode, null), 'string')
    assert.equal(typeof weatherModeStatusText(mode, undefined), 'string')
  }
})

test('label lookup never returns undefined', () => {
  for (const mode of [undefined, null, 'virtual', 'measured', 'junk']) {
    assert.equal(typeof weatherModeLabel(mode), 'string')
    assert.ok(weatherModeLabel(mode).length > 0)
  }
})
