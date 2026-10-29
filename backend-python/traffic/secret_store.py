import base64
import getpass
import hashlib
import hmac
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ALGORITHM = 'FERNET_AES128_CBC_HMAC_SHA256'
ENV_KEY = 'ALC_SECRET_KEY'
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / 'backend-python' / 'data' / 'secrets.db'
DEFAULT_KEY_FILE = PROJECT_ROOT / 'config' / 'alc_secret.key'

SCHEMA = """
CREATE TABLE IF NOT EXISTS secrets (
    name        TEXT PRIMARY KEY,
    ciphertext  BLOB NOT NULL,
    algorithm   TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    rotated_at  TEXT
);
CREATE TABLE IF NOT EXISTS secret_audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    action    TEXT NOT NULL,
    fingerprint TEXT,
    at        TEXT NOT NULL,
    actor     TEXT,
    detail    TEXT
);
"""

class SecretError(RuntimeError):
    pass

class SecretNotFound(SecretError):
    pass

class SecretKeyUnavailable(SecretError):
    pass

class SecretDecryptError(SecretError):
    pass

def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def fingerprint(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]

def redact(text, *secrets):
    result = str(text)
    for secret in secrets:
        if secret and len(str(secret)) >= 4:
            result = result.replace(str(secret), '***REDACTED***')
    return result

def normalise_key(key):
    if isinstance(key, str):
        key = key.encode('utf-8')
    if not isinstance(key, (bytes, bytearray)):
        raise SecretKeyUnavailable(f'密钥必须是 bytes 或 str，收到 {type(key).__name__}')
    raw = bytes(key).strip()
    if not raw:
        raise SecretKeyUnavailable('密钥为空')
    try:
        decoded = base64.b64decode(raw + b'=' * (-len(raw) % 4), altchars=b'-_', validate=True)
    except Exception:
        decoded = None
    if decoded is not None and len(decoded) == 32:
        return raw
    if len(raw) == 64 and all(c in b'0123456789abcdefABCDEF' for c in raw):
        raw = bytes.fromhex(raw.decode('ascii'))
    if len(raw) == 32:
        return base64.urlsafe_b64encode(raw)
    raise SecretKeyUnavailable(
        f'密钥长度不合法：需要 Fernet 密钥（44 字符）或 32 字节原始密钥，实际 {len(raw)} 字节')

def resolve_key(env=None, key_file=None, create=True):
    env = os.environ if env is None else env
    supplied = (env.get(ENV_KEY) or '').strip()
    if supplied:
        return supplied.encode('utf-8'), 'ENV'

    path = Path(key_file) if key_file else DEFAULT_KEY_FILE
    if path.exists():
        raw = path.read_text(encoding='utf-8').strip()
        if not raw:
            raise SecretKeyUnavailable(f'密钥文件为空：{path}')
        return raw.encode('utf-8'), 'FILE'

    if not create:
        raise SecretKeyUnavailable(
            f'未找到密钥：请设置环境变量 {ENV_KEY}，或提供密钥文件 {path}')

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key + b'\n')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key, 'FILE_CREATED'

class SecretStore:

    def __init__(self, path=None, key=None, env=None, key_file=None, create_key=True):
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if key is None:
            key, self.key_source = resolve_key(env=env, key_file=key_file, create=create_key)
        else:
            self.key_source = 'INJECTED'
        try:
            self._fernet = Fernet(normalise_key(key))
        except SecretKeyUnavailable:
            raise
        except Exception as exc:
            raise SecretKeyUnavailable(f'{ENV_KEY} 不是合法的 Fernet 密钥：{type(exc).__name__}') from None
        self._initialise()
        self.key_warning = self._check_key_safety()

    def _check_key_safety(self):
        if self.key_source != 'FILE_CREATED':
            return None
        with self._connect() as connection:
            try:
                existing = connection.execute('SELECT COUNT(*) FROM secrets').fetchone()[0]
            except sqlite3.DatabaseError:
                return None
        if not existing:
            return None
        return (f'已为 {existing} 条既有凭据新建了密钥文件（原密钥丢失）。'
                f'这些凭据当前无法解密，请用 secret_store 重新写入。')

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self):
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _audit(self, connection, name, action, value_fingerprint=None, actor=None, detail=None):
        connection.execute(
            'INSERT INTO secret_audit (name, action, fingerprint, at, actor, detail) VALUES (?,?,?,?,?,?)',
            (name, action, value_fingerprint, _now(), actor, detail),
        )

    def put(self, name, value, actor=None):
        if not name or not str(name).strip():
            raise SecretError('密钥名称不能为空')
        if value is None or value == '':
            raise SecretError(f'拒绝写入空值：{name}')
        token = self._fernet.encrypt(str(value).encode('utf-8'))
        digest = fingerprint(str(value))
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                'SELECT created_at, fingerprint FROM secrets WHERE name=?', (name,)).fetchone()
            if existing is None:
                connection.execute(
                    'INSERT INTO secrets (name, ciphertext, algorithm, fingerprint, created_at, updated_at) '
                    'VALUES (?,?,?,?,?,?)', (name, token, ALGORITHM, digest, now, now))
                action = 'CREATE'
            else:
                connection.execute(
                    'UPDATE secrets SET ciphertext=?, algorithm=?, fingerprint=?, updated_at=?, rotated_at=? WHERE name=?',
                    (token, ALGORITHM, digest, now, now, name))
                action = 'ROTATE'
            self._audit(connection, name, action, digest, actor,
                        'value changed' if existing is not None and existing['fingerprint'] != digest else None)
        return digest

    def get(self, name):
        with self._connect() as connection:
            row = connection.execute(
                'SELECT ciphertext, algorithm FROM secrets WHERE name=?', (name,)).fetchone()
        if row is None:
            raise SecretNotFound(f'未配置密钥：{name}（请先用 secret_store 写入）')
        try:
            return self._fernet.decrypt(row['ciphertext']).decode('utf-8')
        except InvalidToken:
            raise SecretDecryptError(
                f'无法解密 {name}：当前密钥与写入时不一致（密钥来源 {self.key_source}）') from None

    def get_optional(self, name, default=None):
        try:
            return self.get(name)
        except SecretNotFound:
            return default

    def has(self, name):
        with self._connect() as connection:
            return connection.execute(
                'SELECT 1 FROM secrets WHERE name=?', (name,)).fetchone() is not None

    def fingerprint_of(self, name):
        with self._connect() as connection:
            row = connection.execute(
                'SELECT fingerprint, updated_at FROM secrets WHERE name=?', (name,)).fetchone()
        return dict(row) if row else None

    def names(self):
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT name, algorithm, fingerprint, created_at, updated_at FROM secrets ORDER BY name'
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, name, actor=None):
        with self._connect() as connection:
            cursor = connection.execute('DELETE FROM secrets WHERE name=?', (name,))
            if cursor.rowcount:
                self._audit(connection, name, 'DELETE', None, actor)
            return cursor.rowcount

    def audit(self, limit=50):
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT name, action, fingerprint, at, actor, detail FROM secret_audit '
                'ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
        return [dict(row) for row in rows]

CMA_ACCOUNT_EMAIL = 'cma.account_email'
CMA_ACCOUNT_PASSWORD = 'cma.account_password'
CMA_API_USER_ID = 'cma.api_user_id'
CMA_API_PASSWORD = 'cma.api_password'
HUAFENG_API_KEY = 'huafeng.api_key'

def store_default():
    return SecretStore()

def _main(argv):
    store = SecretStore()
    if store.key_warning:
        print(f'[警告] {store.key_warning}', file=sys.stderr)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print('用法：')
        print('  python -m traffic.secret_store list')
        print('  python -m traffic.secret_store audit')
        print('  python -m traffic.secret_store set <名称>        # 从标准输入读取值')
        print('  python -m traffic.secret_store rm  <名称>')
        print(f'密钥来源：{ENV_KEY} 环境变量，或 {DEFAULT_KEY_FILE}')
        return 0
    command = argv[0]
    if command == 'list':
        rows = store.names()
        if not rows:
            print('（未存储任何凭据）')
        for row in rows:
            print(f"{row['name']:<28} {row['algorithm']}  指纹 {row['fingerprint']}  更新 {row['updated_at']}")
        return 0
    if command == 'audit':
        for row in store.audit():
            print(f"{row['at']}  {row['action']:<7} {row['name']:<28} {row['fingerprint'] or '-'}")
        return 0
    if command == 'set':
        if len(argv) < 2:
            print('缺少名称', file=sys.stderr)
            return 2
        name = argv[1]
        value = sys.stdin.readline().rstrip('\n')
        if not value:
            value = getpass.getpass(f'请输入 {name} 的值（不回显）：')
        digest = store.put(name, value, actor='cli')
        print(f'已加密写入 {name}，指纹 {digest}')
        return 0
    if command in ('rm', 'delete'):
        if len(argv) < 2:
            print('缺少名称', file=sys.stderr)
            return 2
        print(f'已删除 {argv[1]}（{store.delete(argv[1], actor="cli")} 行）')
        return 0
    print(f'未知命令：{command}', file=sys.stderr)
    return 2

if __name__ == '__main__':
    raise SystemExit(_main(sys.argv[1:]))
