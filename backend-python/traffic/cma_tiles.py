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
# 回看窗口 = 36 档 × 6 分钟 = 3.6 小时。
#
# 原来是 12 档（72 分钟），依据是"产品 6 分钟一版，一小时足够追上"。这个依据
# 只对**源站正常发布**成立。2026-11-13 凌晨实测：源站最后一版停在 01:54 +08，
# 到 03:10 已停更 76 分钟，12 档刚好差 4 分钟够不着 —— 屏幕上于是整块显示
# 「雷达槽号 未取得」，而源站并没有坏，只是这一夜走得慢。
# 放宽到 3.6 小时后，这种情况会拿到 01:54 那帧，并按 slotAgeMinutes 如实标出
# "X 分钟前"，而不是宣称没有数据。
MAX_LOOKBACK_STEPS = 36
# 命中一帧就缓存 5 分钟；但如果命中的是**旧帧**（源站停更中），只能缓存 2 分钟，
# 否则源站恢复发布后界面还要再看 5 分钟的旧图。
CACHE_SECONDS = 300
STALE_CACHE_SECONDS = 120
STALE_SLOT_MINUTES = 30

# 分档阈值改由 `weather/dbz.py` 定义、这里**再导出同名常量**：
# 名字与取值一字未变（radar_field.py 与三个雷达测试文件不用动），但全仓只剩一个赋值点。
# 以前这里是权威、`weather/radar_public.py` 里自己又打了一遍 32/41，两边就那么漂开了。
from weather.dbz import (  # noqa: F401  (再导出)
    CONVECTIVE_DBZ,
    ECHO_FLOOR_DBZ,
    SEVERE_DBZ,
    STRONG_DBZ,
    THRESHOLDS_DBZ,
)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_CACHE = {}
_WARNED = set()

# zoom 3 覆盖中国本土的最小完整块：x ∈ {5,6}、y ∈ {2,3}，四张。
# 早先只写 (6,2)+(6,3) 两张，是"当时能取到的那两张"，不是覆盖；2026-11-12
# 源站发 (5,2)(6,2)(5,3) 三张、不发 (6,3)，按旧网格就只能拼出东北一角。
# 四张全发是完整覆盖，缺哪张由 ingest_tiles 的 missingTiles 如实记录。
DEFAULT_GRID = ((5, 2), (6, 2), (5, 3), (6, 3))

TILE_FETCH_WORKERS = 2
# 探测阶段的并发：36 个时次各试两个坐标，6 路并发约 2 秒；串行要十几秒。
PROBE_WORKERS = 6
# 一批探测多少个时次。正常情况（源站在发最新一版）第一批就命中，
# 后面的批次根本不发请求 —— 响应变慢只发生在源站真的停更时。
PROBE_BATCH = 12
# 整轮探测的时间预算。超了就按"这一轮没取到"返回，而不是让首屏一直转圈。
PROBE_BUDGET_SECONDS = 25

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

def _probe_slot(attempt, zoom, probes):
    """问一句"这一档还在发布吗"：命中任意一个坐标就算在，不关心命中几个。

    探测与取图分开，是被 3.6 小时回看窗口逼出来的：36 档 × 4 张 = 144 次请求，
    串行要十几秒，而绝大多数时候答案在第一档。先每档只试两个坐标，代价约 1/2。
    """
    last = '探测坐标为空'
    for x, y in probes:
        try:
            fetch_tile(attempt, zoom, x, y)
            return attempt, None
        except RadarTileUnavailable as exc:
            last = f'({x},{y}) {exc}'
    return attempt, last

def _latest_available_slot(slot, zoom, tiles):
    """从新到旧找第一个仍在发布的时次；返回 (时次, 试了几档, 首条错误)。"""
    probes = list(tiles[:2]) if len(tiles) > 1 else list(tiles)
    deadline = time.monotonic() + PROBE_BUDGET_SECONDS
    tried = 0
    first_error = None
    # 最常见的情形是"最新一档就在"。先单独问这一档，命中就直接返回，
    # 常态路径只有 1–2 次请求；批量探测留给源站真的停更的时候。
    attempt, error = _probe_slot(slot, zoom, probes)
    tried += 1
    if error is None:
        return attempt, tried, None
    first_error = f'{slot:%Y-%m-%d %H:%M}Z {error}'
    for batch_start in range(1, MAX_LOOKBACK_STEPS, PROBE_BATCH):
        if time.monotonic() > deadline:
            break
        batch = [slot - dt.timedelta(minutes=CADENCE_MINUTES * step)
                 for step in range(batch_start,
                                   min(batch_start + PROBE_BATCH, MAX_LOOKBACK_STEPS))]
        if not batch:
            break
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, min(PROBE_WORKERS, len(batch)))) as pool:
            outcomes = list(pool.map(lambda item: _probe_slot(item, zoom, probes), batch))
        tried += len(batch)
        for attempt, error in outcomes:
            if error is None:
                return attempt, tried, None
    return None, tried, first_error

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
    used_slot, tried, probe_error = _latest_available_slot(slot, zoom, tiles)

    if used_slot is None:
        value = {'available': False, 'provenance': provenance,
                 'error': f'最近 {tried} 个时次（{tried * CADENCE_MINUTES} 分钟）均不可用：'
                          f'{probe_error}',
                 'slot': None, 'cells': [], 'missingTiles': [list(t) for t in tiles],
                 'degreesPerCell': tile_degrees_per_cell(zoom),
                 'relay': relay_instructions(zoom, grid)}
        _CACHE[key] = {'expires': now_monotonic + 60, 'value': value}
        return {**value, 'cache': 'MISS'}

    # 逐坐标容错：**缺一张不等于这一档没发布。**
    #
    # 原来这里只要有一张失败就整档 break。而源站 2026-11-13 实测四张网格里
    # (6,3) 全天 404、其余三张正常 —— 于是每一档都被判"不可用"，36 档全废，
    # 屏幕上写「雷达槽号 未取得」。缺的坐标照实记进 missingTiles（缺测与
    # "那一块没有回波"在图上长得一样，必须说出来），能用的照常拼。
    gathered = []
    missing = []
    for (x, y), body, error in _fetch_tiles(used_slot, zoom, tiles):
        if error is not None:
            missing.append([x, y])
            continue
        gathered.append((x, y, body))

    if not gathered:
        value = {'available': False, 'provenance': provenance,
                 'error': f'{used_slot:%Y-%m-%d %H:%M} +08 这一档探测时在、取全档时全部失败'
                          f'（{len(missing)} 张），按不可用处理',
                 'slot': None, 'cells': [], 'missingTiles': missing,
                 'degreesPerCell': tile_degrees_per_cell(zoom),
                 'relay': relay_instructions(zoom, grid)}
        _CACHE[key] = {'expires': now_monotonic + 60, 'value': value}
        return {**value, 'cache': 'MISS'}

    instant = slot_instant(used_slot)
    cells = [(x, y, decode_tile(body)) for x, y, body in gathered]
    age_minutes = round((dt.datetime.now(dt.timezone.utc) - instant).total_seconds() / 60, 1)
    value = {
        'available': True, 'provenance': provenance,
        'error': None,
        'slot': instant.isoformat().replace('+00:00', 'Z'),
        'slotLocal': f'{used_slot:%Y-%m-%d %H:%M} +08',
        'slotAgeMinutes': age_minutes,
        'cells': cells, 'degreesPerCell': tile_degrees_per_cell(zoom),
        'gridTiles': sorted((x, y) for x, y, _ in cells),
        'missingTiles': missing,
        'stats': sample_stats([r for _, _, rows in cells for r in rows]),
        'lookbackStepsUsed': tried,
        'relay': {'needed': False},
    }
    ttl = STALE_CACHE_SECONDS if age_minutes > STALE_SLOT_MINUTES else CACHE_SECONDS
    _CACHE[key] = {'expires': now_monotonic + ttl, 'value': value}
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
                '取到后请「原样回传字节」，不要在浏览器里做任何换算或裁剪。',
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

    # 收到的是子集时要把"缺哪几个坐标"记下来：缺测在回波图上与"无回波"长得一模一样，
    # 不写进载荷，下游只会读成"那块天晴"。2026-11-12 源站只发 zoom 3 的 (5,2)(6,2)(5,3)，
    # (6,3) 全天 404 —— 这正是要靠这个字段说清楚的事。
    expected = {tuple(t) for t in DEFAULT_GRID}
    received = {(x, y) for x, y, _ in cells}
    missing = [list(t) for t in sorted(expected - received)]

    instant = slot_instant(used_slot)
    provenance = {
        'provider': 'CMA_DATA_NET', 'dataset': 'RADAR_L3_MST_CREF_GISJPG_Tiles_CR',
        'transport': 'CLIENT_RELAY', 'credentialed': False,
        'cadenceMinutes': CADENCE_MINUTES, 'zoom': zoom,
        'tileFormat': f'{TILE_SIZE}x{TILE_SIZE} big-endian int16, dBZ = value * {SCALE}',
        'retrievedAt': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'missingTiles': missing,
    }
    return {
        'available': True, 'provenance': provenance, 'error': None,
        'slot': instant.isoformat().replace('+00:00', 'Z'),
        'slotLocal': f'{used_slot:%Y-%m-%d %H:%M} +08',
        'slotAgeMinutes': round((dt.datetime.now(dt.timezone.utc) - instant).total_seconds() / 60, 1),
        'cells': cells, 'degreesPerCell': tile_degrees_per_cell(zoom),
        'gridTiles': sorted((x, y) for x, y, _ in cells),
        'missingTiles': missing,
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
