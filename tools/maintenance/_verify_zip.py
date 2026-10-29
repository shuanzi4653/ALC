# -*- coding: utf-8 -*-
"""复验新 zip：条目数、体积、摘要，并与包目录逐条对照。

判据来源 = **目录自己**，不是「我以为打了多少个」：
zip 的条目清单必须与 `ALC-交付-0.9.26-beta/` 下的文件全集逐条相等，
多一条少一条都算异常。这样「打包时漏了目录」或「多带了 .run」都无处遁形。
"""
import hashlib
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import package_dir  # noqa: E402

# 与 `_make_zip.py` 同源：包名取自 `VERSION`（见该文件顶部的说明）。
BASE = Path(os.path.dirname(package_dir()))
NAME = os.path.basename(package_dir())
PKG = BASE / NAME
ZIP = BASE / (NAME + ".zip")
OLD_ZIP = BASE / ("_stale_" + NAME + ".zip")

TOP = NAME + "/"


def main() -> int:
    if not ZIP.exists():
        print("[FAIL] 新 zip 不存在：", ZIP)
        return 1
    raw = ZIP.read_bytes()
    print(f"zip 字节 = {len(raw)}    {len(raw)/1024/1024:.2f} MB")
    print(f"sha256  = {hashlib.sha256(raw).hexdigest()}")
    # 「上一版体积」只是**参照物**，不是判据。参照物被回收之后（2026-10-11 第十一轮
    # 把 `_stale_*` 与旧包一起送进了回收站），这个脚本**曾在这里崩掉** ——
    # 而崩掉的输出读起来像"打包失败"，其实被判的对象一直好好的。
    # 参照物缺席要报成「无法比较」，不能报成「比较失败」（M60）。
    if OLD_ZIP.exists():
        print(f"上一版   = {OLD_ZIP.stat().st_size/1024/1024:.2f} MB")
    else:
        print(f"上一版   = （参照物不在：{OLD_ZIP.name} —— 无法比较体积，不影响本判据）")

    with zipfile.ZipFile(ZIP) as z:
        names = z.namelist()

    # 目录条目单列：上一版 zip 是「只有文件条目」的形状，所以任何目录条目都是
    # 与上一版的形状差异。上一次我把两者混在一个集合里比，于是「10 条目录条目」
    # 被报成「zip 里有、磁盘上没有」——**量具的口径错了，看起来却像产物多了东西**。
    dir_entries = [n for n in names if n.endswith("/")]
    names = [n for n in names if not n.endswith("/")]

    disk = {p.relative_to(PKG).as_posix() for p in PKG.rglob("*") if p.is_file()}
    inzip = {n[len(TOP):] for n in names if n.startswith(TOP)}
    outside = [n for n in names if not n.startswith(TOP)]

    print(f"磁盘文件 {len(disk)} / zip 文件条目 {len(inzip)} / zip 目录条目 {len(dir_entries)}")
    if dir_entries:
        print(f"[FAIL] 出现 {len(dir_entries)} 条目录条目，与上一版形状不同：{dir_entries[:5]}")
    else:
        print("[OK] 无目录条目（与上一版同形）")
    if outside:
        print(f"[FAIL] 有 {len(outside)} 条不在 {TOP} 之下：{outside[:5]}")
    lost = sorted(disk - inzip)
    extra = sorted(inzip - disk)
    if lost:
        print(f"[FAIL] 磁盘上有、zip 里没有（{len(lost)}）:")
        for x in lost[:10]:
            print("   -", x)
    if extra:
        print(f"[FAIL] zip 里有、磁盘上没有（{len(extra)}）:")
        for x in extra[:10]:
            print("   +", x)
    if not (lost or extra):
        print(f"[OK] zip 与目录逐条一致（{len(disk)} 项，无多无少）")
    if outside or lost or extra or dir_entries:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
