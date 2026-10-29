"""清理本仓库的临时/废弃产物（2026-10-11）。

原则（对应用户「废弃的该删就删，做好备份即可」）：
  1. 只碰**已被 `.gitignore` 声明为本地临时件**的目录与文件。仓库自己已经把它们
     判成"不该进版本库"，所以删它们不会丢任何可复现的东西。
  2. 删之前先报**清单与字节数**，删之后再核实**路径真的不在了** ——
     判据只能是"路径还在不在"，工具的成功自述不算（M15 的教训）。
  3. 手写的脚本先打包备份（`backups/scratch-2026-10-11/run-scripts.zip`，已校验 CRC）。
  4. 不碰 `.workbuddy/` —— 它是项目数据，不是缓存（系统约定）。
  5. 不碰 `frontend/node_modules`、`backend-python/.venv`、`backend-java/target`：
     它们体积大但**可再生且是启动必需**，删了要重新装。

用法：
  python tools/maintenance/_clean_scratch.py --report   # 只报告，不动
  python tools/maintenance/_clean_scratch.py --apply    # 执行删除
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

# 整目录清除：仓库的 .gitignore 已声明这些是本地临时件。
PURGE_DIRS = ('.run', '.audit', '.pytest_cache', '.mypy_cache')
# 单个文件：日志与缓存。
PURGE_GLOBS = ('*.log', '*.tmp', '*.temp')
# 绝不触碰。
NEVER = ('.workbuddy', '.git', 'frontend/node_modules', 'backend-python/.venv',
         'backend-java/target', 'backups')


def du(path):
    if path.is_file():
        return path.stat().st_size
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return '%.1f %s' % (n, unit)
        n /= 1024.0


def targets():
    out = []
    for name in PURGE_DIRS:
        p = Path(ROOT) / name
        if p.exists():
            out.append(p)
    for pattern in PURGE_GLOBS:
        for p in Path(ROOT).glob(pattern):
            if p.is_file() and not any(str(p).replace('\\', '/').startswith(
                    str(Path(ROOT) / n).replace('\\', '/')) for n in NEVER):
                out.append(p)
    # 项目自有的 __pycache__（venv / node_modules 除外）
    for base, dirs, _files in os.walk(ROOT):
        rel = os.path.relpath(base, ROOT).replace('\\', '/')
        if any(rel == n or rel.startswith(n + '/') for n in NEVER):
            dirs[:] = []
            continue
        if '__pycache__' in dirs:
            out.append(Path(base) / '__pycache__')
            dirs.remove('__pycache__')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()

    items = targets()
    items.sort(key=lambda p: -du(p))
    total = 0
    print('%-52s %10s' % ('path', 'size'))
    for p in items:
        size = du(p)
        total += size
        print('%-52s %10s' % (str(p.relative_to(ROOT)), human(size)))
    print('-' * 64)
    print('%-52s %10s  (%d items)' % ('TOTAL', human(total), len(items)))

    if not args.apply:
        print('\n(report only -- pass --apply to delete)')
        return 0

    removed, failed = [], []
    for p in items:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as exc:
            failed.append((p, str(exc)))
        else:
            removed.append(p)

    print('\nremoved %d item(s), %d failure(s)' % (len(removed), len(failed)))
    for p, err in failed:
        print('  FAILED %s: %s' % (p, err))

    # 判据：**路径还在不在**（不问工具报了什么）。
    survivors = [str(p.relative_to(ROOT)) for p in items if p.exists()]
    if survivors:
        print('CLEAN FAIL -- %d path(s) still present: %s'
              % (len(survivors), ', '.join(survivors[:8])))
        return 1
    print('CLEAN OK -- every target path is gone; reclaimed %s' % human(total))
    return 0


if __name__ == '__main__':
    sys.exit(main())
