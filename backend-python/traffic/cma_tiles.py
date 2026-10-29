import base64
import concurrent.futures
import datetime as dt
import math
import os
import struct
import time
import urllib.error
import urllib.request

TILE_BASE = os.environ.get(
    'ALC_CMA_TILE_BASE',
    'https://image.data.cma.cn/tiles/China/RADAR_L3_MST_CREF_GISJPG_Tiles_CR').rstrip('/')
TILE_SIZE = 256
BYTES_PER_CELL = 2
MISSING = 32767
SCALE = 0.1
CADENCE_MINUTES = 6
TIMEOUT_SECONDS = 20
MAX_LOOKBACK_STEPS = 12
CACHE_SECONDS = 300

ECHO_FLOOR_DBZ = 15.0
CONVECTIVE_DBZ = 35.0
STRONG_DBZ = 45.0
SEVERE_DBZ = 60.0

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_CACHE = {}
_WARNED = set()

DEFAULT_GRID = ((6, 2), (6, 3))

TILE_FETCH_WORKERS = 2

def _fetch_one(attempt, zoom, x, y):
    try:
        return (x, y), fetch_tile(attempt, zoom, x, y), None
    except RadarTileUnavailable as exc:
        return (x, y), None, str(exc)

def _fetch_tiles(attempt, zoom, tiles):
    tiles = list(tiles)
    if not tiles:
        return []
    workers = max(1, min(TILE_FETCH_WORKERS, len(tiles)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(
            lambda tile: _fetch_one(attempt, zoom, tile[0], tile[1]), tiles))

class RadarTileUnavailable(RuntimeError):
    pass

def _warn_once(key, message):
    if key not in _WARNED:
        _WARNED.add(key)
        print(f'[cma_tiles] {message}')

SLOT_TZ = dt.timezone(dt.timedelta(hours=8))

def latest_slot(now=None):
    moment = (now or dt.datetime.now(dt.timezone.utc)).astimezone(SLOT_TZ)
    minute = (moment.minute // CADENCE_MINUTES) * CADENCE_MINUTES
    return moment.replace(minute=minute, second=0, microsecond=0)

def slot_instant(slot):
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=SLOT_TZ)
    return slot.astimezone(dt.timezone.utc)

def tile_url(slot, zoom, x, y):
    return f'{TILE_BASE}/{slot:%Y%m%d}/{slot:%H}/{slot:%M}/{zoom}/{y}/{x}.bin'

def fetch_tile(slot, zoom=3, x=6, y=3, opener=None):
    url = tile_url(slot, zoom, x, y)
    request = urllib.request.Request(url, headers={'User-Agent': 'ALC-radar/1.0'})
    try:
        with (opener or _OPENER).open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise RadarTileUnavailable(f'HTTP {exc.code}') from None
    except Exception as exc:  # noqa: BLE001 - any transport failure is the same outcome here
        raise RadarTileUnavailable(type(exc).__name__) from None
    expected = TILE_SIZE * TILE_SIZE * BYTES_PER_CELL
    if len(body) != expected:
        raise RadarTileUnavailable(f'瓦片长度 {len(body)}，预期 {expected}')
    return body

def decode_tile(body):
    values = struct.unpack(f'>{TILE_SIZE * TILE_SIZE}h', body)
    return [[None if values[row * TILE_SIZE + column] == MISSING
             else values[row * TILE_SIZE + column] * SCALE
             for column in range(TILE_SIZE)]
            for row in range(TILE_SIZE)]

def tile_degrees_per_cell(zoom):
    return 360.0 / (TILE_SIZE * (2 ** zoom))

def sample_stats(rows):
    present = [value for row in rows for value in row if value is not None]
    if not present:
        return {'cells': TILE_SIZE * TILE_SIZE, 'present': 0, 'echoFraction': 0.0,
                'convectiveFraction': 0.0, 'strongFraction': 0.0,
                'minDbz': None, 'maxDbz': None}
    echo = [value for value in present if value >= ECHO_FLOOR_DBZ]
    return {
        'cells': TILE_SIZE * TILE_SIZE,
        'present': len(present),
        'echoFraction': len(echo) / (TILE_SIZE * TILE_SIZE),
        'convectiveFraction': sum(1 for v in echo if v >= CONVECTIVE_DBZ) / (TILE_SIZE * TILE_SIZE),
        'strongFraction': sum(1 for v in echo if v >= STRONG_DBZ) / (TILE_SIZE * TILE_SIZE),
        'minDbz': min(present), 'maxDbz': max(present),
    }

def frame(zoom=3, grid=None, now=None, force=False):
    key = (zoom, tuple(sorted(grid)) if grid else None)
    cached = _CACHE.get(key)
    now_monotonic = time.monotonic()
    if not force and cached and now_monotonic < cached['expires']:
        return {**cached['value'], 'cache': 'HIT'}

    tiles = list(grid) if grid else DEFAULT_GRID
    provenance = {
        'provider': 'CMA_DATA_NET', 'dataset': 'RADAR_L3_MST_CREF_GISJPG_Tiles_CR',
        'transport': 'PUBLIC_HTTP_TILE', 'credentialed': False,
        'cadenceMinutes': CADENCE_MINUTES, 'zoom': zoom,
        'tileFormat': f'{TILE_SIZE}x{TILE_SIZE} big-endian int16, dBZ = value * {SCALE}',
        'retrievedAt': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
    }
    _warn_once('public', '使用免凭据公开雷达瓦片；该接口无服务等级保证，失败时不产出任何风险几何。')

    slot = latest_slot(now)
    cells = []
    errors = []
    used_slot = None
    for step in range(MAX_LOOKBACK_STEPS):
        attempt = slot - dt.timedelta(minutes=CADENCE_MINUTES * step)
        gathered = []
        failure = None
        for (x, y), body, error in _fetch_tiles(attempt, zoom, tiles):
            if error is not None:
                failure = f'({x},{y}) {error}'
                break
            gathered.append((x, y, body))
        if failure is None:
            used_slot = attempt
            cells = [(x, y, decode_tile(body)) for x, y, body in gathered]
            break
        errors.append(f'{attempt:%Y-%m-%d %H:%M}Z {failure}')

    if used_slot is None:
        value = {'available': False, 'provenance': provenance,
                 'error': '最近 ' + str(MAX_LOOKBACK_STEPS) + ' 个时次均不可用：' + '; '.join(errors[:3]),
                 'slot': None, 'cells': [], 'degreesPerCell': tile_degrees_per_cell(zoom),
                 'relay': relay_instructions(zoom, grid)}
        _CACHE[key] = {'expires': now_monotonic + 60, 'value': value}
        return {**value, 'cache': 'MISS'}

    instant = slot_instant(used_slot)
    combined = [value for _, _, rows in cells for row in rows for value in row]
    value = {
        'available': True, 'provenance': provenance,
        'error': None,
        'slot': instant.isoformat().replace('+00:00', 'Z'),
        'slotLocal': f'{used_slot:%Y-%m-%d %H:%M} +08',
        'slotAgeMinutes': round((dt.datetime.now(dt.timezone.utc) - instant).total_seconds() / 60, 1),
        'cells': cells, 'degreesPerCell': tile_degrees_per_cell(zoom),
        'gridTiles': sorted((x, y) for x, y, _ in cells),
        'stats': sample_stats([r for _, _, rows in cells for r in rows]),
        'lookbackStepsUsed': len(errors),
        'relay': {'needed': False},
    }
    _CACHE[key] = {'expires': now_monotonic + CACHE_SECONDS, 'value': value}
    return {**value, 'cache': 'MISS'}

RELAY_TILE_BYTES = TILE_SIZE * TILE_SIZE * BYTES_PER_CELL

class RelayPayloadRejected(ValueError):
    """中继上来的载荷不合法（长度 / 时次 / 网格）。拒绝而不是尽力解释。"""

def relay_instructions(zoom=3, grid=None):
    return {
        'needed': True,
        'tileBase': TILE_BASE,
        'tileUrlTemplate': f'{TILE_BASE}/{{YYYYMMDD}}/{{HH}}/{{MM}}/{zoom}/{{y}}/{{x}}.bin',
        'zoom': zoom,
        'grid': [list(t) for t in (grid or DEFAULT_GRID)],
        'cadenceMinutes': CADENCE_MINUTES,
        'maxLookbackSteps': MAX_LOOKBACK_STEPS,
        'slotTimezoneOffsetMinutes': 480,
        'tileBytes': RELAY_TILE_BYTES,
        'postTo': '/api/traffic/radar/tiles',
        'note': '服务器出口被源站按 IP 拒绝（整站 403），而浏览器在住宅网络上可直取。'
                '取到后请**原样回传字节**，不要在浏览器里做任何换算或裁剪。',
    }

def _parse_slot(payload):
    """把中继载荷里的时次解析回一个北京时 slot（路径字面值口径）。"""
    if not payload:
        raise RelayPayloadRejected('缺少时次 slot（浏览器必须回报它实际取到的那一档）')
    text = str(payload).strip().replace('Z', '+00:00')
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise RelayPayloadRejected(f'时次格式无法解析：{payload!r}') from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SLOT_TZ)
    local = moment.astimezone(SLOT_TZ)
    if local.minute % CADENCE_MINUTES or local.second or local.microsecond:
        raise RelayPayloadRejected(
            f'时次未落在 {CADENCE_MINUTES} 分钟网格上：{local:%Y-%m-%d %H:%M:%S} +08')
    return local

def ingest_tiles(entries, zoom=3, slot=None, now=None):
    entries = list(entries or [])
    if not entries:
        raise RelayPayloadRejected('中继载荷里没有任何瓦片')

    used_slot = _parse_slot(slot)
    reference = (now or dt.datetime.now(dt.timezone.utc)).astimezone(SLOT_TZ)
    delta_minutes = (reference - used_slot).total_seconds() / 60
    if delta_minutes < -CADENCE_MINUTES:
        raise RelayPayloadRejected(
            f'时次位于未来（{used_slot:%Y-%m-%d %H:%M} +08，比现在早 {-delta_minutes:.0f} 分钟）')
    if delta_minutes > CADENCE_MINUTES * (MAX_LOOKBACK_STEPS + 2):
        raise RelayPayloadRejected(
            f'时次过旧（{used_slot:%Y-%m-%d %H:%M} +08，早于现在 {delta_minutes:.0f} 分钟）')

    cells = []
    for item in entries:
        try:
            x, y = int(item['x']), int(item['y'])
        except (KeyError, TypeError, ValueError) as exc:
            raise RelayPayloadRejected('瓦片条目缺少整数 x/y') from exc
        raw = item.get('data')
        if isinstance(raw, str):
            try:
                body = base64.b64decode(raw, validate=True)
            except Exception as exc:  # noqa: BLE001 - 任何解码失败都是同一个结果
                raise RelayPayloadRejected(f'({x},{y}) data 不是合法 base64') from exc
        elif isinstance(raw, (bytes, bytearray)):
            body = bytes(raw)
        else:
            raise RelayPayloadRejected(f'({x},{y}) data 既不是 base64 字符串也不是字节')
        if len(body) != RELAY_TILE_BYTES:
            raise RelayPayloadRejected(
                f'({x},{y}) 瓦片长度 {len(body)}，预期 {RELAY_TILE_BYTES}')
        cells.append((x, y, decode_tile(body)))
    if not cells:
        raise RelayPayloadRejected('中继载荷里没有任何可用瓦片')

    instant = slot_instant(used_slot)
    provenance = {
        'provider': 'CMA_DATA_NET', 'dataset': 'RADAR_L3_MST_CREF_GISJPG_Tiles_CR',
        'transport': 'CLIENT_RELAY', 'credentialed': False,
        'cadenceMinutes': CADENCE_MINUTES, 'zoom': zoom,
        'tileFormat': f'{TILE_SIZE}x{TILE_SIZE} big-endian int16, dBZ = value * {SCALE}',
        'retrievedAt': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
    }
    return {
        'available': True, 'provenance': provenance, 'error': None,
        'slot': instant.isoformat().replace('+00:00', 'Z'),
        'slotLocal': f'{used_slot:%Y-%m-%d %H:%M} +08',
        'slotAgeMinutes': round((dt.datetime.now(dt.timezone.utc) - instant).total_seconds() / 60, 1),
        'cells': cells, 'degreesPerCell': tile_degrees_per_cell(zoom),
        'gridTiles': sorted((x, y) for x, y, _ in cells),
        'stats': sample_stats([r for _, _, rows in cells for r in rows]),
        'lookbackStepsUsed': None,
    }

def cell_centre_lonlat(x, y, column, row, zoom):
    scale = 2 ** zoom
    world_x = (x + (column + 0.5) / TILE_SIZE) / scale
    world_y = (y + (row + 0.5) / TILE_SIZE) / scale
    longitude = world_x * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * world_y
    latitude = math.degrees(math.atan(math.sinh(n)))
    return longitude, latitude

def status():
    return {
        'provider': 'CMA_DATA_NET', 'dataset': 'RADAR_L3_MST_CREF_GISJPG_Tiles_CR',
        'tileBase': TILE_BASE, 'credentialed': False, 'cadenceMinutes': CADENCE_MINUTES,
        'thresholdsDbz': {'echo': ECHO_FLOOR_DBZ, 'convective': CONVECTIVE_DBZ,
                          'strong': STRONG_DBZ, 'severe': SEVERE_DBZ},
        'note': '公开可访问的组网组合反射率瓦片，无需账号；接口无服务等级保证，'
                '失败时不产出风险几何，由调用方决定降级路径。',
    }
