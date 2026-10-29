"""一行命令发版：本地 → 服务器（JAR + 本次改动的 Python 文件 + VERSION）。

为什么单独写这个文件
--------------------
`docs/云端部署与运维说明.md` 里写的 `.run/cloud/deploy-app.sh` **已经不在盘上了** ——
`.run/` 是临时目录，会被 maintenance timer 清掉。于是最近几轮发版靠的是
"临时敲的那几条 scp / cp / systemctl"，也就是**流程只活在记忆里**。

记忆化的流程有两个具体代价（都真实发生过）：
  · 漏传 VERSION → Python 侧 `FileNotFoundError`、服务反复重启；
  · 只换 jar 不重启 Python → `/v2/overview` 还是旧口径，而界面已经是新包
    （症状："改了但没生效"，而且两处各自都"看起来"正常）。

所以把顺序固化下来，并且**每一步都有可核对的判据**：

  ⓪ 本地：VERSION 与 jar 同名、jar 内前端 == dist          （不一致就不上传）
  ① 服务器：部署前快照（VERSION / 两个 py / 当前 jar 的 md5）
  ② 上传：jar + 本次改动的 python 文件 + VERSION（逐个比 md5）
  ③ 部署：`bin/deploy-remote.sh`（归档旧包 → 原子替换 → 重启 Java → 轮询 → 失败自动回滚）
  ④ Python：替换文件 + `systemctl restart AIC-tianchuang-python`
  ⑤ 收尾：`_verify_release.py --ssh` 22 项全绿才算完成

用法
----
    python tools/deploy/_deploy_release.py --dry-run          # 只打印计划
    python tools/deploy/_deploy_release.py                    # 真发
    python tools/deploy/_deploy_release.py --only-python      # 只发 Python 侧（jar 没变）

`--py` 可以覆盖"哪些 python 文件算改动"。默认按 mtime 与上一次发版比较是不可靠的
（时钟、拷贝都会骗人），所以默认取**显式清单**：`--py a.py --py b.py`；
不给就只发 jar，并在结尾把这件事说出来 —— **不猜**。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAR_DIR = ROOT / 'backend-java' / 'target'
DIST = ROOT / 'frontend' / 'dist'
VERSION_FILE = ROOT / 'VERSION'
KEY = Path.home() / '.ssh' / 'hongsight.pem'
HOST = 'ubuntu@62.234.154.34'
R = '/opt/apps/AIC-tianchuang'
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PROXIED = urllib.request.build_opener()


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], timeout: int = 900, quiet: bool = False) -> subprocess.CompletedProcess:
    if not quiet:
        print('  $', ' '.join(cmd[:6]) + (' …' if len(cmd) > 6 else ''))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 and not quiet:
        print(proc.stdout[-1500:] if proc.stdout else '')
        print(proc.stderr[-1500:] if proc.stderr else '')
    return proc


def sh(cmd: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return run(['ssh', '-i', str(KEY), '-o', 'StrictHostKeyChecking=no',
                '-o', 'ConnectTimeout=15', HOST, cmd], timeout=timeout)


def scp(paths: list[Path], dest: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return run(['scp', '-i', str(KEY), *[str(p) for p in paths], f'{HOST}:{dest}'], timeout=timeout)


def js_hash(html: str) -> str:
    m = re.search(r'assets/index-([A-Za-z0-9_-]+)\.js', html or '')
    return m.group(1) if m else ''


def die(msg: str, code: int = 1) -> None:
    print('FATAL: ' + msg)
    sys.exit(code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--skip-jar', action='store_true', help='只发 Python 侧与 VERSION')
    ap.add_argument('--py', action='append', default=[], help='要上传的 python 文件（仓库相对路径）')
    ap.add_argument('--py-tree', action='store_true',
                    help='整棵 backend-python 一起发（大改版用；跳过 data/ .venv tests __pycache__）')
    # `--jar` 只为两件事存在：① 负向自检（喂一个名不副实的包必须被拒）；
    # ② 回滚时把 `app/releases/` 里那一份重新推上去。默认永远取 target 下最新那个。
    ap.add_argument('--jar', default='')
    ap.add_argument('--base', default='https://tianchuang.shuanzi.site')
    args = ap.parse_args()

    version = VERSION_FILE.read_text(encoding='utf-8').strip()
    if args.jar:
        jar = Path(args.jar)
    else:
        jars = sorted(JAR_DIR.glob('tianchuang-server-*.jar'), key=lambda p: p.stat().st_mtime)
        jar = jars[-1] if jars else None
    if not jar or not jar.is_file():
        die('backend-java/target 下没有 jar，先跑 .run/build_manual.ps1')
    if version not in jar.name:
        die(f'jar 名 {jar.name} 与 VERSION {version} 不一致 —— 先重新打包，别上传混版产物')
    index = DIST / 'index.html'
    if not index.is_file():
        die('frontend/dist 缺失')
    local_js = js_hash(index.read_text(encoding='utf-8'))
    with jar.open('rb') as fh:
        import zipfile
        with zipfile.ZipFile(fh) as zf:
            jar_js = js_hash(zf.read('BOOT-INF/classes/static/index.html').decode('utf-8'))
    if local_js != jar_js:
        die(f'jar 内前端 {jar_js} != dist {local_js} —— 包是旧的，先重新打包')

    py_files = [ROOT / p for p in args.py]
    for p in py_files:
        if not p.is_file():
            die(f'找不到 {p}')
    if args.py_tree:
        base = ROOT / 'backend-python'
        skip = {'data', '.venv', '__pycache__', 'tests', 'experiments'}
        py_files = [p for p in base.rglob('*.py')
                    if p.is_file() and not (set(p.relative_to(base).parts) & skip)]

    staging_dir = Path(tempfile.mkdtemp())
    print(f'版本 {version} · jar {jar.name} · {jar.stat().st_size} B · md5 {md5(jar)}')
    print(f'前端 chunk {local_js} · Python 文件 {len(py_files)} 个')
    if args.dry_run:
        for p in py_files:
            print('  将上传', p.relative_to(ROOT).as_posix(), md5(p))
        print('（--dry-run，未做任何改动）')
        return 0

    # ---- ① 部署前快照 ----
    ts = time.strftime('%Y%m%d-%H%M%S')
    snap = f'{R}/backup/pre-deploy-{ts}'
    rc = sh(f'set -e; mkdir -p {snap}; cp -p {R}/VERSION {snap}/VERSION; '
            f'cp -p {R}/backend-python/traffic/v2.py {snap}/v2.py 2>/dev/null || true; '
            f'md5sum {R}/app/tianchuang-server.jar > {snap}/jar.md5; echo {snap}')
    if rc.returncode != 0:
        die('部署前快照失败（不带着"没有可退的东西"上线）')
    print('快照:', snap)

    # ---- ② 上传 ----
    if not args.skip_jar:
        tmp_jar = f'/tmp/aic-{version}.jar'
        if scp([jar], tmp_jar).returncode != 0:
            die('jar 上传失败')
        rc = sh(f'md5sum {tmp_jar}')
        remote = rc.stdout.split()[0] if rc.stdout.split() else ''
        if remote != md5(jar):
            die(f'上传后 md5 不一致：线上 {remote} / 本地 {md5(jar)}')
        print('jar 上传并校验一致')

    relative: list[str] = []
    if py_files and args.py_tree:
        # 整棵树走 tar：几十个文件逐个 scp 要开几十条连接，慢且容易半截；
        # 打成一个包、传一次、解开，再用清单逐文件校验。
        py_base = ROOT / 'backend-python'
        relative = [p.relative_to(py_base).as_posix() for p in py_files]
        manifest = staging_dir / 'MANIFEST.md5'
        with manifest.open('w', encoding='utf-8', newline='') as fh:
            for p, rel in zip(py_files, relative):
                fh.write('%s  %s\n' % (md5(p), rel))
        archive_path = staging_dir / 'py-tree.tgz'
        rc = run(['tar', 'czf', str(archive_path), '-C', str(py_base), *relative], quiet=True)
        if rc.returncode != 0:
            die('打 tar 失败')
        sh('mkdir -p /tmp/aic-py')
        for src, dest in ((archive_path, '/tmp/aic-py/py-tree.tgz'), (manifest, '/tmp/aic-py/MANIFEST.md5')):
            if scp([src], dest).returncode != 0:
                die('上传 %s 失败' % dest)
        rc = sh('md5sum /tmp/aic-py/py-tree.tgz')
        if (rc.stdout.split() or [''])[0] != md5(archive_path):
            die('tar 上传后 md5 不一致')
        if scp([VERSION_FILE], '/tmp/aic-py/__VERSION__').returncode != 0:
            die('VERSION 上传失败')
        print('Python 树 %d 个文件已上传（tar %.0f KB）' % (len(py_files), archive_path.stat().st_size / 1024))
        py_files = []          # 后面按 tar 展开，不再逐文件复制
    elif py_files:
        remote_tmp = '/tmp/aic-py'
        server_root = sh(f'mkdir -p {remote_tmp} && echo ok')
        if server_root.returncode != 0:
            die('建临时目录失败')
        py_base = ROOT / 'backend-python'
        relative = [p.relative_to(py_base).as_posix() for p in py_files]
        for p, rel in zip(py_files, relative):
            dest = f'{remote_tmp}/{rel}'
            sh(f'mkdir -p {os.path.dirname(dest)}')
            if scp([p], dest).returncode != 0:
                die(f'{rel} 上传失败')
            rc = sh(f'md5sum {dest}')
            if (rc.stdout.split() or [''])[0] != md5(p):
                die(f'{rel} 上传后 md5 不一致')
        # VERSION 一起走：Python 侧读项目根这份，漏传就是启动时反复重启。
        if scp([VERSION_FILE], f'{remote_tmp}/__VERSION__').returncode != 0:
            die('VERSION 上传失败')
        rc = sh(f'md5sum {remote_tmp}VERSION')
        if (rc.stdout.split() or [''])[0] != md5(VERSION_FILE):
            die('VERSION 上传后 md5 不一致')
        print(f'Python 文件 {len(py_files)} 个 + VERSION 上传并校验一致')

    # ---- ③ 部署 jar ----
    if not args.skip_jar:
        rc = sh(f'sudo -u ubuntu {R}/bin/deploy-remote.sh /tmp/aic-{version}.jar')
        if rc.returncode != 0:
            die('deploy-remote.sh 失败（它自己会尝试回滚，先看 journalctl）')
        print('jar 已替换并重启 Java')

    # ---- ④ Python 侧 ----
    if relative:
        rc = sh(f'cd {R}/backend-python && tar xzf /tmp/aic-py/py-tree.tgz && '
                'sed "s#  #  #" /tmp/aic-py/MANIFEST.md5 | md5sum -c --quiet - && echo CHECK_OK')
        if rc.returncode != 0 or 'CHECK_OK' not in rc.stdout:
            die('Python 树解开后校验不通过：' + rc.stdout[-600:])
        rc = sh(f'cp /tmp/aic-py/__VERSION__ {R}/VERSION; cat {R}/VERSION')
        if rc.stdout.strip().splitlines()[-1].strip() != version:
            die(f'服务器 VERSION 写成了 {rc.stdout.strip()}')
        rc = sh('sudo systemctl restart AIC-tianchuang-python; sleep 10; '
                'systemctl is-active AIC-tianchuang AIC-tianchuang-python')
        if rc.returncode != 0 or rc.stdout.split().count('active') != 2:
            die('Python 单元未起来：' + rc.stdout.strip())
        print('Python 侧已替换并重启（%d 个文件）' % len(relative))
        relative = []
    if py_files:
        mapping = [f'cp /tmp/aic-py/{rel} {R}/backend-python/{rel}'
                   for rel in relative]
        rc = sh('set -e; ' + '; '.join(mapping) +
                f'; cp /tmp/aic-py/__VERSION__ {R}/VERSION; cat {R}/VERSION')
        if rc.returncode != 0:
            die('Python 文件替换失败')
        if rc.stdout.strip().splitlines()[-1].strip() != version:
            die(f'服务器 VERSION 写成了 {rc.stdout.strip()}，期望 {version}')
        rc = sh('sudo systemctl restart AIC-tianchuang-python; sleep 10; '
                'systemctl is-active AIC-tianchuang AIC-tianchuang-python')
        if rc.returncode != 0 or rc.stdout.split().count('active') != 2:
            die('Python 单元未起来：' + rc.stdout.strip())
        print('Python 侧已替换并重启')

    # ---- ⑤ 收尾自检 ----
    sh('rm -rf /tmp/aic-py')
    verify = ROOT / 'tools' / 'maintenance' / '_verify_release.py'
    proc = subprocess.run([sys.executable, str(verify), '--base', args.base, '--ssh'])
    if proc.returncode != 0:
        print('\n发版自检未全绿 —— 别对外宣布已上线；回滚见 backup/pre-deploy-' + ts)
        return 1
    print('\n发版完成：自检全绿')
    return 0


if __name__ == '__main__':
    sys.exit(main())
