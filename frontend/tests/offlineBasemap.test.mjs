import test from 'node:test'
import assert from 'node:assert/strict'
import {
  BASEMAP_CHANNEL_OFFLINE, BASEMAP_CHANNEL_ONLINE, BASEMAP_CHANNEL_PENDING,
  BASEMAP_OFFLINE_AFTER_FAILURES, OFFLINE_BASEMAP_COLORS, OFFLINE_BASEMAP_NOTICE,
  basemapChannelAfterSignal, basemapChannelLabel, basemapChannelNames,
  basemapFallbackVisible, basemapIsOffline, basemapSignalFromError, basemapStatusText,
  classifyMapError,
} from '../src/traffic/runtime.js'

// The offline basemap is a *downgrade*, not an error, and the whole point of the
// three-state channel is that the two must not be confused. A wrong verdict here
// is not cosmetic: it either shows a "you are offline" alarm to someone with a
// working connection, or hides the fact that the operator is looking at a ~1 km
// simplification. Both are misreadings of the same kind -- asserting a fact the
// evidence does not support.

test('an absent or unknown channel resolves to online, not offline', () => {
  // Defaulting to OFFLINE would mean every render starts by claiming the network
  // is down. Defaulting to ONLINE merely says "we have not seen a failure yet",
  // which is true and is also what the style actually attempts first.
  for (const value of [undefined, null, '', 'OFFLINE', 'offline ', 0, {}, 'nonsense']) {
    assert.equal(basemapSignalFromError('glyph'), null, String(value))
  }
  assert.equal(basemapChannelLabel(undefined), basemapChannelNames[BASEMAP_CHANNEL_ONLINE])
  assert.equal(basemapChannelLabel('nonsense'), basemapChannelNames[BASEMAP_CHANNEL_ONLINE])
})

test('only the exact offline and pending strings are recognised', () => {
  assert.equal(basemapIsOffline(BASEMAP_CHANNEL_OFFLINE), true)
  assert.equal(basemapIsOffline('online'), false)
  assert.equal(basemapIsOffline('pending'), false)
  assert.equal(basemapChannelLabel(BASEMAP_CHANNEL_PENDING), '底图载入中')
  assert.equal(basemapChannelLabel('pending'), '底图载入中')
})

test('the fallback layer is drawn only when the channel is provably offline', () => {
  // The load-bearing case is PENDING. If the fallback rendered while pending, the
  // offline outline would flash on every cold start; if it rendered never, the
  // feature would do nothing. One answer per state, no overlap.
  assert.equal(basemapFallbackVisible(BASEMAP_CHANNEL_ONLINE), false)
  assert.equal(basemapFallbackVisible(BASEMAP_CHANNEL_PENDING), false)
  assert.equal(basemapFallbackVisible(BASEMAP_CHANNEL_OFFLINE), true)
})

test('a single missing tile is not an outage', () => {
  // Tiles load on demand, so panning across a province edge reliably produces a
  // few 404s for the provider's coverage boundary -- the same distinction
  // classifyMapError already makes for the error banner.
  assert.equal(basemapSignalFromError('Failed to load resource: 404'), 'no-tiles')
  assert.equal(basemapChannelAfterSignal(BASEMAP_CHANNEL_ONLINE, 1), BASEMAP_CHANNEL_ONLINE)
  assert.equal(basemapChannelAfterSignal(BASEMAP_CHANNEL_PENDING, 1), BASEMAP_CHANNEL_PENDING)
})

test('an outage is declared only at the threshold, and one event later is decisive', () => {
  assert.equal(
    basemapChannelAfterSignal(BASEMAP_CHANNEL_ONLINE, BASEMAP_OFFLINE_AFTER_FAILURES - 1),
    BASEMAP_CHANNEL_ONLINE,
    '阈值前不得降级',
  )
  assert.equal(
    basemapChannelAfterSignal(BASEMAP_CHANNEL_ONLINE, BASEMAP_OFFLINE_AFTER_FAILURES),
    BASEMAP_CHANNEL_OFFLINE,
    '达到阈值必须降级',
  )
  assert.equal(
    basemapChannelAfterSignal(BASEMAP_CHANNEL_ONLINE, BASEMAP_OFFLINE_AFTER_FAILURES + 99),
    BASEMAP_CHANNEL_OFFLINE,
  )
})

test('failures never un-set an established offline verdict', () => {
  // The recovery path is reportMap() seeing real tiles and resetting the count --
  // it is deliberately NOT "the counter is low again", because the counter is
  // reset in the same breath. Reversing the verdict here would need the missing
  // evidence that triggered it in the first place.
  for (const count of [0, 1, BASEMAP_OFFLINE_AFTER_FAILURES - 1]) {
    assert.equal(basemapChannelAfterSignal(BASEMAP_CHANNEL_OFFLINE, count), BASEMAP_CHANNEL_OFFLINE, String(count))
  }
})

test('nonsense failure counts do not downgrade', () => {
  for (const value of [undefined, null, NaN, -1, 'many', {}, []]) {
    assert.equal(basemapChannelAfterSignal(BASEMAP_CHANNEL_ONLINE, value), BASEMAP_CHANNEL_ONLINE, String(value))
  }
  assert.equal(basemapChannelAfterSignal(BASEMAP_CHANNEL_PENDING, undefined), BASEMAP_CHANNEL_PENDING)
  // Infinity is not a count an increment can produce, but if it ever arrived it
  // must read as "many failures", not as "no failures".
  assert.equal(basemapChannelAfterSignal(BASEMAP_CHANNEL_ONLINE, Infinity), BASEMAP_CHANNEL_OFFLINE)
})

test('only failures that can be attributed to a remote source affect the channel', () => {
  // A missing sprite or glyph is a cosmetic gap in a layer we asked for; a
  // cancelled request is the camera moving. Neither says anything about whether
  // the basemap provider is reachable, and treating them as an outage would
  // trigger the fallback on a healthy connection.
  assert.equal(basemapSignalFromError('glyph .pbf font range missing'), null)
  assert.equal(basemapSignalFromError('sprite atlas not found'), null)
  assert.equal(basemapSignalFromError('AbortError: the operation was aborted'), null)
  assert.equal(basemapSignalFromError(''), null)
  assert.equal(basemapSignalFromError(undefined), null)
  // These do: the provider is unreachable, or has no data here.
  assert.equal(basemapSignalFromError('Failed to fetch'), 'no-tiles')
  assert.equal(basemapSignalFromError('net::ERR_CONNECTION_TIMED_OUT'), 'no-tiles')
  assert.equal(basemapSignalFromError('style is not done loading'), 'no-tiles')
})

test('signals never contradict classifyMapError', () => {
  // basemapSignalFromError is defined in terms of classifyMapError; if the two
  // ever disagree, the map would report a category the channel logic did not
  // consider. Pin the dependency so a future edit to the classifier is caught.
  const cases = [
    'Failed to fetch', '404 not found', 'tile missing', 'glyph error',
    'sprite problem', 'style load failed', 'request aborted', 'who knows',
  ]
  for (const message of cases) {
    const label = classifyMapError(message)
    const signal = basemapSignalFromError(message)
    if (signal === 'no-tiles') {
      assert.ok(['TILE_404', 'NETWORK', 'STYLE'].includes(label), `${message} -> ${label}`)
    }
  }
})

test('the offline status text says what the picture is and never claims precision', () => {
  const text = basemapStatusText(BASEMAP_CHANNEL_OFFLINE, { city: '', buildingCount: 0 })
  assert.match(text, /离线底图/)
  assert.match(text, /低精度/)
  assert.ok(!/城市道路|立体建筑/.test(text), '离线态不得声称载入了城市道路或建筑')
})

test('pending reports loading, never a conclusion', () => {
  const text = basemapStatusText(BASEMAP_CHANNEL_PENDING, {})
  assert.equal(text, '正在载入城市地图')
  assert.ok(!/离线/.test(text), 'PENDING 不得说离线')
  assert.ok(!/已载入/.test(text), 'PENDING 不得说已载入')
  // An error already on screen outranks the generic wording.
  assert.equal(basemapStatusText(BASEMAP_CHANNEL_PENDING, { error: '自定义错误' }), '自定义错误')
})

test('online status text keeps the building-count distinction', () => {
  assert.match(basemapStatusText(BASEMAP_CHANNEL_ONLINE, { buildingCount: 3, city: '沈阳市' }), /城市道路与立体建筑已载入/)
  assert.match(basemapStatusText(BASEMAP_CHANNEL_ONLINE, { buildingCount: 0, city: '沈阳市' }), /无建筑要素/)
  assert.match(basemapStatusText(BASEMAP_CHANNEL_ONLINE, { buildingCount: 0, city: '' }), /全域城市地图已载入/)
})

test('the offline notice names the source, the precision and the recovery', () => {
  // Labelling is the contract: this file ships a deliberately coarse boundary,
  // and an operator comparing it to the online map must not conclude the system
  // lost geometry. The sentence has to carry all three facts, so it is asserted
  // rather than trusted to survive editing.
  assert.match(OFFLINE_BASEMAP_NOTICE, /离线/)
  assert.match(OFFLINE_BASEMAP_NOTICE, /内置/)
  assert.match(OFFLINE_BASEMAP_NOTICE, /低精度/)
  assert.match(OFFLINE_BASEMAP_NOTICE, /自动切回/)
})

test('every channel has a label and the offline palette is distinct from online hues', () => {
  for (const channel of [BASEMAP_CHANNEL_ONLINE, BASEMAP_CHANNEL_OFFLINE, BASEMAP_CHANNEL_PENDING]) {
    assert.equal(typeof basemapChannelNames[channel], 'string')
    assert.ok(basemapChannelNames[channel].length > 0)
  }
  // The offline land colour must not be mistaken for the online background
  // (city-map-style.json background is #0b1926): the fallback has to read as a
  // deliberate surface, not as the empty background it replaces.
  assert.notEqual(OFFLINE_BASEMAP_COLORS.land.toLowerCase(), '#0b1926')
  for (const key of ['land', 'coast', 'boundary', 'label', 'labelHalo']) {
    assert.match(OFFLINE_BASEMAP_COLORS[key], /^#[0-9a-f]{6}$/i, key)
  }
})
