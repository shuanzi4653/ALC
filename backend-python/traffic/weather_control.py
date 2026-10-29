import datetime as dt
import threading
import time

from . import cma_tiles, weather_sim
import workspace as workspace_ctx

MODE_MEASURED = 'measured'
MODE_VIRTUAL = 'virtual'
MODES = (MODE_MEASURED, MODE_VIRTUAL)

DEFAULT_MODE = MODE_MEASURED

DEFAULT_SEED = 42

_LOCK = threading.RLock()
_START = {
    'mode': DEFAULT_MODE,
    'seed': DEFAULT_SEED,
    'changedAt': None,
    'changedBy': None,
    'reason': None,
    'measuredFrames': 0,
    'virtualFrames': 0,
    'relay': None,
    'relayFrames': 0,
}

RELAY_TTL_SECONDS = 600

_STATES = {}
MAX_WORKSPACES = 64

def _state(workspace=None):
    """取（必要时创建）该工作区的状态。调用方不必持锁；本函数自己取。"""
    key = workspace if workspace is not None else workspace_ctx.current()
    with _LOCK:
        state = _STATES.get(key)
        if state is None:
            while len(_STATES) >= MAX_WORKSPACES:
                _STATES.pop(next(iter(_STATES)))
            state = dict(_START)
            _STATES[key] = state
        return state

def _iso_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')

def mode(workspace=None):
    with _LOCK:
        return _state(workspace)['mode']

def set_mode(target, *, seed=None, actor=None, reason=None, workspace=None):
    if target not in MODES:
        raise ValueError(f'未知气象模式 {target!r}，可用：{MODES}')
    if seed is not None:
        seed = int(seed)
    with _LOCK:
        state = _state(workspace)
        previous = state['mode']
        state.update({
            'mode': target,
            'changedAt': _iso_now(),
            'changedBy': actor or 'api',
            'reason': reason,
        })
        if seed is not None:
            state['seed'] = seed
            state['reason'] = reason or f'演示数据快照编号切换为 {seed}'
    return {
        'previous': previous, 'mode': target, 'changed': previous != target,
        **status(workspace),
    }

def seed(workspace=None):
    with _LOCK:
        return _state(workspace)['seed']

def _bump(key, workspace=None):
    with _LOCK:
        _state(workspace)[key] += 1

def ingest_relay(payload, workspace=None):
    with _LOCK:
        _state(workspace)['relay'] = {'at': time.monotonic(), 'value': payload}
    _bump('relayFrames', workspace)
    return {
        'stored': True,
        'slot': payload.get('slot'), 'slotLocal': payload.get('slotLocal'),
        'stats': payload.get('stats'), 'gridTiles': payload.get('gridTiles'),
        'ttlSeconds': RELAY_TTL_SECONDS,
    }

def _fresh_relay(workspace=None):
    """该工作区里尚在存活期内的中继帧；过期即就地丢弃。"""
    with _LOCK:
        state = _state(workspace)
        relay = state['relay']
        if relay is None:
            return None
        if time.monotonic() - relay['at'] > RELAY_TTL_SECONDS:
            state['relay'] = None
            return None
        return relay['value']

def radar_frame(slot=None, force=False, workspace=None):
    current = mode(workspace)
    if current == MODE_VIRTUAL:
        stamp = slot or dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
        value = weather_sim.frame(seed=seed(workspace), slot=stamp)
        _bump('virtualFrames', workspace)
        return {
            **value,
            'mode': MODE_VIRTUAL,
            'virtualNotice': {
                'synthetic': True,
                'statement': '本帧为程序生成的模拟对流回波，不是观测数据。'
                             '几何形态与强度分档仿照主流气象雷达产品，仅用于演示与重现。',
                'realAlternative': 'measured',
            },
        }
    relayed = _fresh_relay(workspace)
    if relayed is not None:
        _bump('measuredFrames', workspace)
        return {**relayed, 'mode': MODE_MEASURED}
    value = cma_tiles.frame(force=force)
    _bump('measuredFrames', workspace)
    return {**value, 'mode': MODE_MEASURED}

def is_virtual(workspace=None):
    return mode(workspace) == MODE_VIRTUAL

def frame_identity(weather_mode=None, workspace=None):
    if weather_mode is None:
        weather_mode = mode(workspace)
    if weather_mode == MODE_VIRTUAL:
        return ''
    relayed = _fresh_relay(workspace)
    return str((relayed or {}).get('slot') or '')

def status(workspace=None):
    with _LOCK:
        snapshot = dict(_state(workspace))
    return {
        'mode': snapshot['mode'],
        'seed': snapshot['seed'],
        'defaultMode': DEFAULT_MODE,
        'availableModes': list(MODES),
        'changedAt': snapshot['changedAt'],
        'changedBy': snapshot['changedBy'],
        'reason': snapshot['reason'],
        'framesServed': {
            'measured': snapshot['measuredFrames'],
            'virtual': snapshot['virtualFrames'],
            'relayed': snapshot['relayFrames'],
        },
        'clientRelay': {
            'supported': True,
            'present': snapshot['relay'] is not None,
            'ttlSeconds': RELAY_TTL_SECONDS,
            'postTo': '/api/traffic/radar/tiles',
            'why': '瓦片源对数据中心出口整站 403（连 / 与 /robots.txt 都拒），'
                   '但对住宅 IP 正常，且返回 Access-Control-Allow-Origin: *，'
                   '因此浏览器可以代取、服务器仍是唯一的解码与派生出口。',
            'scopedTo': 'workspace',
        },
        'measuredSource': {
            'provider': 'CMA_DATA_NET',
            'dataset': 'RADAR_L3_MST_CREF_GISJPG_Tiles_CR',
            'cadenceMinutes': cma_tiles.CADENCE_MINUTES,
            'thresholdsDbz': {'echo': cma_tiles.ECHO_FLOOR_DBZ,
                              'convective': cma_tiles.CONVECTIVE_DBZ,
                              'strong': cma_tiles.STRONG_DBZ,
                              'severe': cma_tiles.SEVERE_DBZ},
        },
        'virtualSource': weather_sim.status(),
        'trafficNote': '交通数据全程为模拟生成，不受本开关影响：'
                       '系统不存在“实测交通”，因此也没有虚拟/实测之分。',
        'note': '本开关只切换气象与雷达通道。实测模式下实测源失败会如实报告，'
                '不会用虚拟帧顶替。',
    }

def reset(workspace=None):
    with _LOCK:
        if workspace is None:
            _STATES.clear()
        else:
            _state(workspace).update(_START)
    return status(workspace)
