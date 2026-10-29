import os
from datetime import datetime, timedelta, timezone

import httpx

from .secret_store import (
    CMA_ACCOUNT_EMAIL,
    CMA_ACCOUNT_PASSWORD,
    CMA_API_PASSWORD,
    CMA_API_USER_ID,
    SecretError,
    SecretStore,
    store_default,
)

API_BASE = os.environ.get('ALC_CMA_API_BASE', 'http://api.data.cma.cn:8090/api').strip()
DATA_FORMAT = 'json'
DATA_CODES = {'CREF_PNG': 'RADA_L3_MST_V3_CREF_PNG'}
INTERFACE_BY_TIME = 'getRadaFileByTimeRange'
INTERFACE_BY_TIME_AND_STATION = 'getRadaFileByTimeRangeAndStaId'
ELEMENTS = 'Station_Id_C,DATETIME,FORMAT,FILE_NAME'
PUBLISHED_WINDOW_DAYS = 7
TRUST_ENV = os.environ.get('ALC_CMA_TRUST_ENV', '0').strip() == '1'
STRICT_TRANSPORT = os.environ.get('ALC_CMA_STRICT_TRANSPORT', '0').strip() == '1'
TIMEOUT = httpx.Timeout(20, connect=6)

_warned = set()

class RadarUnavailable(RuntimeError):
    pass

def safe_url(url, *extra_secrets):
    from .secret_store import redact
    return redact(url, *extra_secrets)

def credentials(store=None):
    store = store or store_default()
    try:
        user_id = store.get(CMA_API_USER_ID)
        password = store.get(CMA_API_PASSWORD)
    except SecretError as exc:
        raise RadarUnavailable(
            f'雷达数据凭据不可用：{exc}。请先执行 '
            f'"python -m traffic.secret_store set {CMA_API_USER_ID}" 与 '
            f'"python -m traffic.secret_store set {CMA_API_PASSWORD}"。'
        ) from None
    return user_id, password

def parse_minute(value, label):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    for fmt in ('%Y%m%d%H%M%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        raise RadarUnavailable(f'{label} 时间格式无法识别：{text}（应为 YYYYMMDDHHMISS）') from None

def format_minute(moment):
    return moment.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S')

def validate_window(start, end):
    begin, finish = parse_minute(start, '起始'), parse_minute(end, '结束')
    if finish <= begin:
        raise RadarUnavailable('雷达时间范围必须递增')
    span = finish - begin
    if span > timedelta(days=PUBLISHED_WINDOW_DAYS):
        raise RadarUnavailable(
            f'雷达时间范围跨度 {span}，超过平台公布的最近 {PUBLISHED_WINDOW_DAYS} 天访问限制')
    oldest = datetime.now(timezone.utc) - timedelta(days=PUBLISHED_WINDOW_DAYS)
    if begin < oldest - timedelta(hours=1):
        raise RadarUnavailable(
            f'起始时间 {begin.isoformat()} 早于平台最近 {PUBLISHED_WINDOW_DAYS} 天窗口')
    return begin, finish

def build_params(user_id, password, start, end, station_ids=None, data_code='CREF_PNG'):
    if data_code not in DATA_CODES:
        raise RadarUnavailable(
            f'未核实的雷达资料编码：{data_code}；已核实：{sorted(DATA_CODES)}')
    begin, finish = validate_window(start, end)
    params = {
        'userId': user_id,
        'pwd': password,
        'dataFormat': DATA_FORMAT,
        'dataCode': DATA_CODES[data_code],
        'timeRange': f'[{format_minute(begin)},{format_minute(finish)}]',
        'elements': ELEMENTS,
    }
    if station_ids:
        cleaned = [str(item).strip() for item in station_ids if str(item).strip()]
        if cleaned:
            params['interfaceId'] = INTERFACE_BY_TIME_AND_STATION
            params['staIDs'] = ','.join(cleaned)
            return params
    params['interfaceId'] = INTERFACE_BY_TIME
    return params

def _warn_once(key, message):
    if key not in _warned:
        _warned.add(key)
        print(f'[cma_radar] {message}')

def _records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    code = payload.get('returnCode')
    if code is not None and str(code) not in ('0', '2000', 'success'):
        message = payload.get('returnMessage') or payload.get('message') or '未知错误'
        raise RadarUnavailable(f'平台返回错误码 {code}：{message}')
    for key in ('DS', 'ds', 'data', 'rows', 'result'):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ('DS', 'ds', 'data', 'rows', 'list'):
                if isinstance(value.get(nested), list):
                    return value[nested]
    return []

def normalise(record):
    lowered = {str(key).lower(): value for key, value in (record or {}).items()}
    return {
        'stationId': lowered.get('station_id_c') or lowered.get('stationid'),
        'datetime': lowered.get('datetime'),
        'format': lowered.get('format'),
        'fileName': lowered.get('file_name') or lowered.get('filename'),
        'fileUrl': lowered.get('file_url') or lowered.get('fileurl'),
    }

def query_files(start, end, station_ids=None, data_code='CREF_PNG', store=None, client=None):
    retrieved = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    provenance = {
        'provider': 'CMA_DATA_NET', 'dataset': DATA_CODES.get(data_code, data_code),
        'transport': 'HTTP_QUERY_CREDENTIALS', 'retrievedAt': retrieved,
        'windowLimitDays': PUBLISHED_WINDOW_DAYS,
    }
    if STRICT_TRANSPORT and API_BASE.startswith('http://'):
        return {'available': False, 'files': [], 'provenance': provenance,
                'error': '已启用严格传输策略，拒绝通过明文 HTTP 发送凭据'}
    try:
        user_id, password = credentials(store)
        params = build_params(user_id, password, start, end, station_ids, data_code)
    except RadarUnavailable as exc:
        return {'available': False, 'files': [], 'provenance': provenance, 'error': str(exc)}

    provenance['interfaceId'] = params['interfaceId']
    provenance['timeRange'] = params['timeRange']
    provenance['stationFilter'] = params.get('staIDs') or 'ALL'
    _warn_once('transport', '凭据通过明文 HTTP 查询串传输，请在受信网络内使用，并避免记录完整请求 URL。')

    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT, trust_env=TRUST_ENV)
    try:
        response = client.get(API_BASE, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        return {'available': False, 'files': [], 'provenance': provenance,
                'error': f'平台返回 HTTP {exc.response.status_code}'}
    except httpx.HTTPError as exc:
        return {'available': False, 'files': [], 'provenance': provenance,
                'error': f'雷达接口网络失败：{type(exc).__name__}'}
    except ValueError:
        return {'available': False, 'files': [], 'provenance': provenance,
                'error': '雷达接口返回内容不是合法 JSON'}
    finally:
        if owned:
            client.close()

    try:
        records = _records(payload)
    except RadarUnavailable as exc:
        return {'available': False, 'files': [], 'provenance': provenance, 'error': str(exc)}

    files = [normalise(record) for record in records if isinstance(record, dict)]
    files = [item for item in files if item['fileName']]
    provenance['fileCount'] = len(files)
    return {'available': True, 'files': files, 'provenance': provenance, 'error': None}

def status(store=None):
    store = store or SecretStore()
    report = {'provider': 'CMA_DATA_NET', 'apiBase': API_BASE,
              'datasets': dict(DATA_CODES), 'windowLimitDays': PUBLISHED_WINDOW_DAYS,
              'transport': 'HTTP_QUERY_CREDENTIALS', 'strictTransport': STRICT_TRANSPORT}
    if getattr(store, 'key_warning', None):
        report['keyWarning'] = store.key_warning
    known = {CMA_API_USER_ID, CMA_API_PASSWORD, CMA_ACCOUNT_EMAIL, CMA_ACCOUNT_PASSWORD}
    report['credentials'] = [
        {'name': row['name'], 'fingerprint': row['fingerprint'], 'updatedAt': row['updated_at']}
        for row in store.names() if row['name'] in known
    ]
    report['ready'] = store.has(CMA_API_USER_ID) and store.has(CMA_API_PASSWORD)
    if not report['ready']:
        report['hint'] = (
            '尚未写入 API 凭据。请先在数据网完成资料订购，再从订单页确认 userId，'
            f'然后执行 python -m traffic.secret_store set {CMA_API_USER_ID} 与 '
            f'python -m traffic.secret_store set {CMA_API_PASSWORD}。'
        )
    return report
