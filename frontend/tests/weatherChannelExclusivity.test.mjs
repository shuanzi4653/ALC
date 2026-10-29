import test from 'node:test'
import assert from 'node:assert/strict'
import {
  WEATHER_CHANNEL_MODEL, WEATHER_CHANNEL_RADAR,
  closureBreakdown, closureReasons, weatherChannelLabel, weatherChannelNote,
  weatherChannelState, weatherClosureReasons,
} from '../src/traffic/runtime.js'

// Two rules that exist because the screen was making a claim the data did not
// support. Both are pure functions of the payload, so they are pinned here
// rather than left to a .vue file that cannot be tested.

// --- rule 1: the two weather layers are INDEPENDENT -------------------------
//
// This rule used to say the opposite: the two channels were "mutually exclusive"
// and turning both on hid the model field. That was a real defect, not a
// preference -- the fixed controlled airspace (禁飞区) is drawn as part of the
// same layer group, so hiding it to keep two weather sources apart also removed
// the statutory airspace from the map. The user's report was exactly that:
// 「气象与雷达不要合并，不然我看不到禁飞区了」.
//
// The corrected contract: visibility is the switches, verbatim. Neither layer
// may ever suppress the other, and nothing may be hidden implicitly.

test('neither weather layer ever suppresses the other', () => {
  for (const showWeather of [true, false]) {
    for (const showRadar of [true, false]) {
      const state = weatherChannelState({ showWeather, showRadar })
      // The layer flags are the switches, with no precedence and no override.
      assert.equal(state.modelVisible, showWeather,
        `modelVisible wrong for showWeather=${showWeather} showRadar=${showRadar}`)
      assert.equal(state.radarVisible, showRadar,
        `radarVisible wrong for showWeather=${showWeather} showRadar=${showRadar}`)
    }
  }
})

test('both weather layers can be visible at once', () => {
  // The specific thing the old rule forbade, and the reason 禁飞区 disappeared.
  const both = weatherChannelState({ showWeather: true, showRadar: true })
  assert.equal(both.modelVisible, true)
  assert.equal(both.radarVisible, true)
})

test('nothing is ever hidden implicitly', () => {
  // The old implementation reported a hiddenChannel and printed a note about a
  // layer "已临时隐藏". Any reappearance of a non-null hiddenChannel means a
  // layer is being taken away from the operator again.
  for (const showWeather of [true, false]) {
    for (const showRadar of [true, false]) {
      const state = weatherChannelState({ showWeather, showRadar })
      assert.equal(state.hiddenChannel, null,
        `a layer was hidden for showWeather=${showWeather} showRadar=${showRadar}`)
      assert.equal(weatherChannelNote(state), '',
        `a suppression note was emitted for showWeather=${showWeather} showRadar=${showRadar}`)
    }
  }
})

test('the active marker tracks which layers are on, without deciding them', () => {
  assert.equal(weatherChannelState({ showWeather: true, showRadar: false }).active, WEATHER_CHANNEL_MODEL)
  assert.equal(weatherChannelState({ showWeather: false, showRadar: true }).active, WEATHER_CHANNEL_RADAR)
  // Both on names both channels -- it is a description, not a winner.
  const both = weatherChannelState({ showWeather: true, showRadar: true })
  assert.match(both.active, new RegExp(WEATHER_CHANNEL_MODEL))
  assert.match(both.active, new RegExp(WEATHER_CHANNEL_RADAR))
  // Neither on: no channel, and nothing is drawn.
  assert.equal(weatherChannelState({ showWeather: false, showRadar: false }).active, null)
})

test('the radar toggle caption follows the mode, not a fixed string', () => {
  assert.match(weatherChannelLabel('virtual'), /模拟/)
  assert.match(weatherChannelLabel('measured'), /实测/)
  assert.notEqual(weatherChannelLabel('virtual'), weatherChannelLabel('measured'))
  // An unknown mode is a measurement (same rule as normalizeWeatherMode), so it
  // must not pick up the 模拟 caption.
  assert.match(weatherChannelLabel(undefined), /实测/)
})

// --- rule 2: a closure count must not imply the weather did it --------------
//
// The summary card used to caption 计划关闭 with a single cause. On a day with no
// weather on the map the number still read as if the weather had closed those
// flights, when every one of them was closed by the statutory airspace, the
// turn-radius envelope or a declared resource slot.

test('outcome codes are not closure causes', () => {
  // A flight that was accepted still carries a reason, so the tally covers the
  // whole plan. Counting CLEAR as a reason for closing would be nonsense.
  for (const outcome of ['CLEAR', 'WEATHER_DETOUR']) {
    assert.equal(closureReasons.has(outcome), false, outcome)
  }
  for (const cause of ['STATIC_AIRSPACE_BLOCKED', 'TURN_RADIUS_OR_BOUNDARY_LIMIT',
    'ALTITUDE_PROFILE_LIMIT', 'NO_GEOMETRIC_PATH',
    'SEPARATION_RESOURCE_OR_TIME_LIMIT', 'MANUAL_SUSPEND']) {
    assert.equal(closureReasons.has(cause), true, cause)
  }
})

test('weather closures are a subset of all closures', () => {
  for (const reason of weatherClosureReasons) {
    assert.equal(closureReasons.has(reason), true, reason)
  }
})

test('a clear day reports no weather cause even with closures', () => {
  const text = closureBreakdown({
    closed: 12, closedByWeather: 0,
    closedByReason: {
      STATIC_AIRSPACE_BLOCKED: 5, TURN_RADIUS_OR_BOUNDARY_LIMIT: 4,
      NO_GEOMETRIC_PATH: 3, CLEAR: 200, WEATHER_DETOUR: 8,
    },
  })
  assert.match(text, /无气象原因/)
  assert.doesNotMatch(text, /CLEAR/)
  assert.doesNotMatch(text, /已绕开/)  // WEATHER_DETOUR is an outcome, not a closure
  assert.match(text, /固定管制区/)
})

test('a weather closure is counted as such', () => {
  assert.match(closureBreakdown({ closed: 3, closedByWeather: 3, closedByReason: { WEATHER_BLOCKED: 3 } }), /气象 3 班/)
})

test('no closures and no plan are distinguished from each other', () => {
  assert.equal(closureBreakdown({ closed: 0, closedByReason: {} }), '本轮无关闭')
  assert.equal(closureBreakdown(undefined), '等待计划')
  assert.equal(closureBreakdown(null), '等待计划')
})

test('the breakdown reads the closure-only tally, not the fleet census', () => {
  // The real shape the service publishes: `closedByReason` is a census of the
  // whole fleet and is ~98% CLEAR, while `closedByClosureReason` holds only the
  // flights that were actually refused. Reading the wrong one printed the
  // accepted flights as if they were closure causes.
  const text = closureBreakdown({
    closed: 123, closedByWeather: 0,
    closedByReason: { CLEAR: 7637, BEYOND_PLANNING_HORIZON: 88, SEPARATION_RESOURCE_OR_TIME_LIMIT: 35 },
    closedByClosureReason: { BEYOND_PLANNING_HORIZON: 88, SEPARATION_RESOURCE_OR_TIME_LIMIT: 35 },
  })
  assert.doesNotMatch(text, /7637/)
  // 88 + 35 == 123, so the listed causes account for every closure and the
  // remainder line must not appear.
  assert.doesNotMatch(text, /其他/)
  assert.match(text, /超出推演时段 88/)
})

test('closures with no recognised cause are reported as a remainder, not hidden', () => {
  // The listed causes cover two of three closures. Silently dropping the third
  // would make the card add up to less than the number beside it, which is the
  // same class of dishonesty as the original single-cause caption.
  const text = closureBreakdown({
    closed: 30, closedByWeather: 0,
    closedByClosureReason: { STATIC_AIRSPACE_BLOCKED: 10, NO_GEOMETRIC_PATH: 10, UNKNOWN_NEW_CAUSE: 10 },
  })
  assert.match(text, /其他 10/)
})

test('an old payload without the closure-only key still filters the census', () => {
  // Fallback path: a payload written before `closedByClosureReason` existed.
  // The reason-set filter must still keep the outcome codes out.
  const text = closureBreakdown({
    closed: 9, closedByWeather: 0,
    closedByReason: { STATIC_AIRSPACE_BLOCKED: 6, NO_GEOMETRIC_PATH: 3, CLEAR: 400, WEATHER_DETOUR: 12 },
  })
  assert.doesNotMatch(text, /CLEAR/)
  assert.doesNotMatch(text, /已绕开/)
  assert.match(text, /固定管制区 6/)
})

test('the breakdown stays short enough for a summary card', () => {
  const text = closureBreakdown({
    closed: 40, closedByWeather: 2,
    closedByReason: {
      STATIC_AIRSPACE_BLOCKED: 10, TURN_RADIUS_OR_BOUNDARY_LIMIT: 9,
      NO_GEOMETRIC_PATH: 8, ALTITUDE_PROFILE_LIMIT: 7,
      SEPARATION_RESOURCE_OR_TIME_LIMIT: 6, WEATHER_BLOCKED: 2,
    },
  })
  // At most three causes are listed, so the string cannot grow with the tally.
  assert.ok(text.length < 120, `too long: ${text}`)
})
