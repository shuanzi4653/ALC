import contextlib
import contextvars
import re

HEADER = 'X-ALC-Workspace'
QUERY = 'ws'

PATTERN = re.compile(r'^[A-Za-z0-9_-]{6,64}$')
UNIDENTIFIED = ''

_CURRENT = contextvars.ContextVar('alc_workspace', default=UNIDENTIFIED)

def normalize(value):
    """合法则原样返回，否则落回「未标识」。"""
    text = (value or '').strip()
    return text if PATTERN.match(text) else UNIDENTIFIED

def current():
    return _CURRENT.get()

def use(value):
    return _CURRENT.set(normalize(value))

@contextlib.contextmanager
def bind(value):
    token = _CURRENT.set(normalize(value))
    try:
        yield
    finally:
        _CURRENT.reset(token)

def reset(token):
    _CURRENT.reset(token)

def from_request(request):
    return normalize(request.headers.get(HEADER) or request.query_params.get(QUERY))
