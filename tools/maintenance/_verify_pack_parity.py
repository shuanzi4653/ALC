# -*- coding: utf-8 -*-
"""M75：交付包 ↔ **仓库当前状态** 逐字节对照（打包后的固定一步）。

为什么它必须在 `tools/` 而不是某次会话的临时目录
------------------------------------------------
这条判据是**每一次发布都要跑**的（M75 把它定为"打包后的固定一步"）。
它曾经只作为一次性脚本存在于 `tools/` 之外 —— 而那正是 **ISS-0.9.25-06 /
ISS-0.9.26-06** 已经付过一次代价的形态：**每轮都要用的工具住在用完即弃的目录里，
下一轮就只剩"再手写一遍"**（手写＝没有闸门）。

为什么它不能省
--------------
打包侧的三条自检（`_verify_handoff_pack.py` 的应有项/排除项、`_verify_zip.py` 的
zip↔目录一致）**参照物全在包内部**：只问"我列的在不在"、"两边是否一致" ——
而"两边同装上一版"时**一致本身没有意义**。所以参照物必须是**仓库当前状态**：

    包内每一个文件  vs  仓库里同一个路径的文件  —— 逐字节比 sha256

输出四类读数：`same / differ / only-in-pack / only-in-repo`。
**只有 `differ == 0 且 only-in-pack == 0` 才算通过**；`only-in-repo` 是**正常的**
（包按设计排除 `backups/`、`artifacts/`、`.run/`、`tools/` 等开发侧目录），
故只作参考打印、不参与判定 —— 把"正常的排除"报成失败会让这条判据第一天就被忽略（M63）。

    _verify_pack_parity.py              对照当前包与当前仓库
    _verify_pack_parity.py <包目录>      对照指定包目录
    _verify_pack_parity.py --self-test   负向对照：证明它咬得住

只读。exit 0 一致 / 1 有不一致 / 2 量不成（包不存在或为空 —— M60：**"量不成"
与"量出来是坏的"必须是不同的出口**）。
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo import ROOT, package_dir  # noqa: E402

SKIP_DIRS = {'.git', '__pycache__', '.venv', 'node_modules'}


def _digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def walk(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace('\\', '/')
            out[rel] = full
    return out


def compare(pack, repo):
    """返回 (same, differ, only_pack, only_repo)，四类相对路径。"""
    packed, live = walk(pack), walk(repo)
    same, differ, only_pack = [], [], []
    for rel, pfull in sorted(packed.items()):
        if rel not in live:
            only_pack.append(rel)
        elif _digest(pfull) == _digest(live[rel]):
            same.append(rel)
        else:
            differ.append(rel)
    only_repo = sorted(set(live) - set(packed))
    return same, differ, only_pack, only_repo


def self_test():
    """M29 / M74：判据必须能对自己的负向输入变红，且不能过宽。

    两个方向都要证，缺一不可：
      * **咬得住** —— 一对**等长不同内容**的文件必须被报成 differ。
        用"等长"作夹具不是随手挑的：本项目上一轮刚被这个形态咬过
        （**ISS-0.9.26-09**：`_diff_pack.py` 用文件大小当内容的代理量，
        等长替换被判成"未变"）。**夹具必须照抄真实形态。**
      * **不过宽** —— 内容真的相同就**不得**报 differ，否则判据放宽成"什么都算变"。
    """
    with tempfile.TemporaryDirectory() as pa, tempfile.TemporaryDirectory() as pb:
        pack, repo = Path(pa), Path(pb)
        (pack / 'sub').mkdir()
        (repo / 'sub').mkdir()
        (pack / 'same.txt').write_bytes(b'identical\n')
        (repo / 'same.txt').write_bytes(b'identical\n')
        (pack / 'code.js').write_bytes(b'#ff2d24\n')      # 8 B
        (repo / 'code.js').write_bytes(b'#e08a45\n')      # 8 B —— 等长，一个字符不同
        (pack / 'sub' / 'only_pack.txt').write_bytes(b'x\n')

        same, differ, only_pack, only_repo = compare(pack, repo)

        problems = []
        if 'code.js' not in differ:
            problems.append('等长不同内容未判为 differ：differ=%r' % (differ,))
        if 'same.txt' in differ or 'same.txt' not in same:
            problems.append('相同内容被误判：same=%r differ=%r' % (same, differ))
        if only_pack != ['sub/only_pack.txt']:
            problems.append('only-in-pack 读数不对：%r' % (only_pack,))

    if problems:
        for problem in problems:
            print('  FAIL %s' % problem)
        print('self-test FAILED')
        return 1
    print('[OK] self-test：等长不同内容 -> differ；相同内容 -> same；'
          'only-in-pack 可识别（三个方向都有牙齿）')
    return 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    pack = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(package_dir())
    if not pack.is_dir():
        print('[CANNOT MEASURE] 包目录不存在：%s' % pack)
        return 2
    repo = Path(ROOT)
    if not walk(pack):
        print('[CANNOT MEASURE] 包内一个文件都没有 —— 量具没量成，不能当通过')
        return 2

    same, differ, only_pack, only_repo = compare(pack, repo)

    print('包目录      : %s' % pack)
    print('包内文件    : %d' % (len(same) + len(differ) + len(only_pack)))
    print('逐字节一致  : %d' % len(same))
    print('内容不同    : %d' % len(differ))
    for rel in differ:
        print('   DIFFER      %s' % rel)
    print('仅包内有    : %d' % len(only_pack))
    for rel in only_pack:
        print('   ONLY-IN-PACK %s' % rel)
    # 正常的排除面，只作参考：把"按设计排除"报成失败会让判据被整体忽略（M63）。
    print('仅仓库有    : %d（参考值 —— 包按设计排除开发侧目录）' % len(only_repo))

    if differ or only_pack:
        print('M75 FAIL -- 包不是当轮仓库的逐字节副本')
        return 1
    print('M75 PASS -- 包内每个文件都与仓库同路径文件逐字节一致')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
