"""Independently verify the sealed credential store actually seals.

Self-reported success from the writing process is not evidence, so this checks
the artefacts directly: for every stored credential the decrypted value must not
appear anywhere in the raw bytes of secrets.db, the key must live outside the
database, and both files must be gitignored.

Deliberately contains **no plaintext credential**: the expected value is
obtained by decrypting, so nothing sensitive lives in source control.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import subprocess
from pathlib import Path


from traffic.secret_store import (  # noqa: E402
    DEFAULT_DB,
    DEFAULT_KEY_FILE,
    SecretStore,
    fingerprint,
)

print('数据库存在  :', DEFAULT_DB.exists(), DEFAULT_DB)
print('密钥文件存在:', DEFAULT_KEY_FILE.exists(), DEFAULT_KEY_FILE)

store = SecretStore()
rows = store.names()
if not rows:
    print('（凭据库为空）')
    raise SystemExit(0)

raw = DEFAULT_DB.read_bytes()
print(f'共 {len(rows)} 条凭据')
for row in rows:
    name = row['name']
    value = store.get_optional(name)
    if value is None:
        print(f'  {name:<24} 无法解密 <<< 需修复')
        continue
    leaked = value.encode('utf-8') in raw
    digest_ok = fingerprint(value) == row['fingerprint']
    print(f'  {name:<24} 明文残留 {"是 <<< 泄露" if leaked else "否"}  '
          f'指纹一致 {"是" if digest_ok else "否 <<< 需修复"}  '
          f'值长度 {len(value)}')

# An audit trail must never carry a value, only a fingerprint.
audit_text = str(store.audit())
print('审计含任一明文 :', any(store.get_optional(row['name']) in audit_text
                              for row in rows if store.get_optional(row['name'])))
print('names() 含任一明文:', any(store.get_optional(row['name']) in str(rows)
                                 for row in rows if store.get_optional(row['name'])))
if getattr(store, 'key_warning', None):
    print('[警告]', store.key_warning)

for path in (DEFAULT_DB, DEFAULT_KEY_FILE):
    result = subprocess.run(['git', 'check-ignore', '-v', str(path)],
                            cwd=str(ROOT), capture_output=True, text=True)
    print(f'  gitignore {path.name:<18} {result.stdout.strip() or "(未被忽略 <<< 需修复)"}')
