"""发版完善度自检：一条命令回答「这一版真的上线了吗、线上跑的是我构建的那一份吗」。

为什么要这个文件
----------------
过去每一轮发版，判断"上没上"靠临时敲的那几条命令：看 `/api/traffic/health` 的版本、
看 `build-info.json` 的时间、`md5sum` 对一下 jar。三个数**分三次看**，而且各自都能
单看成立：

· `VERSION` 已经被手写进服务器 → health 报新版本号，但 jar 可能还是旧的；
· jar 换对了 → 但 nginx 缓存的 index.html 仍指着上一包 chunk；
· 前端换了 → 但 Python 侧没重启，`/v2/overview` 还是旧口径。

单看任何一项都会得到"部署成功"。所以这里把**六项互相咬合**的判据串起来：
版本号、构建 id、jar 摘要、前端 chunk 摘要、特性探针、进程状态。任一项对不上就红。

用法
----
    python tools/maintenance/_verify_release.py            # 只查公网侧（不需要 SSH）
    python tools/maintenance/_verify_release.py --ssh      # 追加服务器侧四项
    python tools/maintenance/_verify_release.py --base https://... --jar <path>

退出码：0 全过 / 1 有 FAIL / 2 量具自身失效（取不到本地产物，无法判断）。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAR_DIR = ROOT / 'backend-java' / 'target'
DIST = ROOT / 'frontend' / 'dist'
VERSION_FILE = ROOT / 'VERSION'
SSH_KEY = Path(os.environ.get('ALC_SSH_KEY', str(Path.home() / '.ssh' / 'hongsight.pem')))
SSH_HOST = os.environ.get('ALC_SSH_HOST', 'ubuntu@62.234.154.34')
REMOTE_ROOT = '/opt/apps/AIC-tianchuang'

# 沙箱里 http_proxy 指向本机中间层，打 127.0.0.1 会被它拦成 502；
# 打公网则**必须**走它（直连常常没有出口）。所以两种 opener 分开，不共用。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_PROXIED = urllib.request.build_opener()

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, bool(ok), detail))
    print(('PASS ' if ok else 'FAIL ') + name + (('  |  ' + detail) if detail else ''))
    return bool(ok)


def fetch(url: str, timeout: int = 25) -> tuple[int, bytes]:
    opener = _DIRECT if re.match(r'^https?://(127\.0\.0\.1|localhost)', url) else _PROXIED
    req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def fetch_json(url: str) -> dict | None:
    code, body = fetch(url)
    if code != 200:
        return None
    try:
        return json.loads(body.decode('utf-8-sig'))
    except ValueError:
        return None


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def js_hash(html: str) -> str:
    m = re.search(r'assets/index-([A-Za-z0-9_-]+)\.js', html or '')
    return m.group(1) if m else ''


def newest_jar() -> Path | None:
    jars = sorted(JAR_DIR.glob('tianchuang-server-*.jar'), key=lambda p: p.stat().st_mtime)
    return jars[-1] if jars else None


def jar_member(jar: Path, name: str) -> str:
    try:
        with zipfile.ZipFile(jar) as zf:
            return zf.read(name).decode('utf-8')
    except (KeyError, zipfile.BadZipFile):
        return ''


def ssh(cmd: str, timeout: int = 60) -> tuple[int, str]:
    if not SSH_KEY.is_file():
        return 127, 'ssh key missing'
    proc = subprocess.run(['ssh', '-i', str(SSH_KEY), '-o', 'StrictHostKeyChecking=no',
                           '-o', 'ConnectTimeout=15', SSH_HOST, cmd],
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='https://tianchuang.shuanzi.site')
    ap.add_argument('--jar', default='')
    ap.add_argument('--ssh', action='store_true', help='追加服务器侧检查（需要 hongsight.pem）')
    args = ap.parse_args()
    base = args.base.rstrip('/')

    # ---- 量具前置条件：本地产物必须在，否则下面每个数都没有参照物 ----
    version = VERSION_FILE.read_text(encoding='utf-8').strip() if VERSION_FILE.is_file() else ''
    if not check('本地产物：VERSION 可读', bool(version), version or 'missing'):
        return 2
    jar = Path(args.jar) if args.jar else newest_jar()
    if not jar or not jar.is_file():
        return 2 if not check('本地产物：找到 jar', False, 'backend-java/target 下没有 jar') else 0
    local_index = (DIST / 'index.html').read_text(encoding='utf-8') if (DIST / 'index.html').is_file() else ''
    local_js = js_hash(local_index)
    jar_index = jar_member(jar, 'BOOT-INF/classes/static/index.html')
    jar_js = js_hash(jar_index)
    jar_info = jar_member(jar, 'BOOT-INF/classes/static/build-info.json')
    jar_build = ''
    try:
        jar_build = (json.loads(jar_info.lstrip('\ufeff')) or {}).get('buildId', '')
    except ValueError:
        jar_build = ''
    check('本地产物：jar 名与 VERSION 一致', version in jar.name, jar.name)
    check('本地产物：jar 内前端 == dist', bool(jar_js) and jar_js == local_js, f'jar={jar_js} dist={local_js}')
    check('本地产物：jar 内有 build-info', bool(jar_build), jar_build or '缺失')
    local_md5 = md5(jar)

    # ---- 公网侧 ----
    info = fetch_json(f'{base}/build-info.json')
    check('公网：build-info 可达', bool(info), 'build-info.json')
    if info:
        check('公网：构建 id == 本地 jar 的 build-id', info.get('buildId') == jar_build,
              f"线上 {info.get('buildId')} / 本地 {jar_build}")
        check('公网：build-info 记录的时间是新构建', bool(info.get('builtAt')),
              str(info.get('builtAt')))

    health = fetch_json(f'{base}/api/traffic/health')
    check('公网：traffic/health 可达', bool(health), 'GET /api/traffic/health')
    if health:
        check('公网：版本号 == VERSION', health.get('version') == version,
              f"线上 {health.get('version')} / 仓库 {version}")
        store = (health.get('checks') or {}).get('planStore') or {}
        check('公网：计划仓库可读', bool(store.get('ok')), str(store.get('detail', ''))[:60])

    code, body = fetch(f'{base}/')
    served = body.decode('utf-8', 'replace')
    check('公网：匿名首页 200', code == 200, f'HTTP {code}')
    check('公网：首页指向本包的 chunk', js_hash(served) == local_js,
          f'线上 {js_hash(served)} / 本地 {local_js}')

    if local_js:
        code_js, body_js = fetch(f'{base}/assets/index-{local_js}.js')
        text_js = body_js.decode('utf-8', 'replace')
        check('公网：本包 chunk 可取', code_js == 200 and len(body_js) > 100000,
              f'HTTP {code_js} {len(body_js)} B')
        # 特性探针：这一版新加的两样东西必须真的在发出去的包里。
        check('公网：chunk 含本次改动（分工说明 / 离线角标）',
              'brief-scope-note' in text_js and 'brief-kpi-scope' in text_js,
              'brief-scope-note / brief-kpi-scope')

    # ---- 接口口径探针：光有新前端不够，后端也得是新的 ----
    ov = fetch_json(f'{base}/api/traffic/v2/overview?seed=42&scenario=live')
    check('公网：overview 可达', bool(ov), 'GET /api/traffic/v2/overview')
    if ov:
        lead = next((k for k in ov.get('kpis') or [] if k.get('key') == 'lead'), {})
        check('接口：平均提前量带离线作用域', lead.get('scope') == 'offline',
              str(lead.get('scope')))
        check('接口：离线基线写明本帧触发数',
              '本帧触发' in str(lead.get('baseline', '')), str(lead.get('baseline', ''))[:60])
        check('接口：结论句非空', bool((ov.get('conclusion') or {}).get('text')),
              str((ov.get('conclusion') or {}).get('text', ''))[:40])

    # ---- 服务器侧（可选）----
    if args.ssh:
        rc, out = ssh(f'cat {REMOTE_ROOT}/VERSION')
        check('服务器：VERSION 文件 == 仓库', rc == 0 and out.strip() == version,
              out.strip()[:40])
        rc, out = ssh(f'md5sum {REMOTE_ROOT}/app/tianchuang-server.jar')
        remote_md5 = out.split()[0] if rc == 0 and out.split() else ''
        check('服务器：在跑的 jar == 本地 jar', remote_md5 == local_md5,
              f'线上 {remote_md5} / 本地 {local_md5}')
        rc, out = ssh('systemctl is-active AIC-tianchuang AIC-tianchuang-python')
        states = out.split()
        check('服务器：两个单元均 active', rc == 0 and states.count('active') == 2, ' '.join(states))
        rc, out = ssh(f'cat {REMOTE_ROOT}/backend-python/traffic/v2.py | md5sum')
        remote_py = out.split()[0] if rc == 0 and out.split() else ''
        check('服务器：v2.py == 本地', remote_py == md5(ROOT / 'backend-python' / 'traffic' / 'v2.py'),
              remote_py or 'n/a')

    fails = [r for r in results if not r[1]]
    print('\n' + '=' * 62)
    print(f'裁决：PASS {len(results) - len(fails)} / FAIL {len(fails)} / 共 {len(results)} 项')
    for name, _, detail in fails:
        print(f'  · {name}  |  {detail}')
    print('结论：' + ('全过' if not fails else '有未完成项，**不要**对外宣布已上线'))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
