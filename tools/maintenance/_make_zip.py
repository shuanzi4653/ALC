# -*- coding: utf-8 -*-
"""按「只有文件条目」的形状重打交付包 zip，与上一版同形。

为什么不用 `Compress-Archive`：它会给**目录**也写条目，于是 zip 条目数
（321）与包内文件数（311）不相等，而上一版的 zip 恰好是 310 条目 = 310 文件
（无目录条目）。两种 zip 解压结果相同，但「形状」变了就是个**没有解释的差异**
——本项目的规矩是把这种差异消掉，而不是写一句"无损"糊过去。

判据：条目数 == 包内文件数，且条目名逐条 == 磁盘相对路径（见 verify_zip.py）。
"""
import hashlib
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import package_dir  # noqa: E402

# 包名与压缩包名**都取自 `VERSION`**，不写死 —— 这四个打包脚本（`_make_zip` /
# `_verify_zip` / `_zip_smoke` / `_diff_pack`）此前各自写死了一份 `0.9.26-beta`，
# 于是 0.9.26 → 0.9.27 时四个一起**静默指着已不存在的目录**：
# `_make_zip.py` 报「包目录不存在」而 `_diff_pack.py` 把整包报成「仅旧包有」。
# `_repo.package_dir()` 的 docstring 记着同一处缺陷修过一次 —— 那次只修了两个调用方。
BASE = Path(os.path.dirname(package_dir()))
NAME = os.path.basename(package_dir())
PKG = BASE / NAME
ZIP = BASE / (NAME + ".zip")
TOP = NAME


def _previous_note(base: Path, name: str) -> str:
    """如实报「上一版多大」，取不到就说取不到。

    为什么要有这个函数：这一行原来**写死** `（上一版 3.73 MB）`。那个数字是 0.9.2x
    时代的，之后每打一次包都照样印出来 —— 读起来像"本轮从 3.73 涨到 4.12"，
    实际上一版的真实体积是 4.08 MB（0.9.34）。**一个永不变化、且永远不会报错的
    对照数字，比没有对照更坏**：它把"没有比较"伪装成"比较过了"（M21 那一类）。

    现在按**版本号**在同一个目录里找真正的前一个包：找不到、或它的 zip 已被删掉，
    就明写「参照物不在」，与本仓库其余量具的口径一致（`_verify_zip.py` 同款措辞）。
    """
    import re
    pat = re.compile(r"^(?P<stem>.*?)(?P<v>\d+\.\d+\.\d+)(?P<tail>-beta)$")
    cur = pat.match(name)
    if not cur:
        return "（包名里没解析出版本号 —— 不比较体积）"
    cur_v = tuple(int(x) for x in cur.group("v").split("."))
    best = None
    for d in base.iterdir():
        m = pat.match(d.name)
        if not m or d.name == name:
            continue
        if m.group("stem") != cur.group("stem") or m.group("tail") != cur.group("tail"):
            continue
        v = tuple(int(x) for x in m.group("v").split("."))
        if v < cur_v and (best is None or v > best[0]):
            best = (v, d)
    if best is None:
        return "（上一版参照物不在 —— 不比较体积）"
    # 注意：**不能用 `with_suffix('.zip')`** —— 包名 `ALC-交付-0.9.34-beta` 里的最后一个点
    # 属于版本号，`Path.suffix` 会把它读成 `.34-beta`，于是 `with_suffix` 得到
    # `ALC-交付-0.9.zip`（一个从不存在的路径），判据就永远报"参照物不在"而永远不红。
    prev_zip = best[1].parent / (best[1].name + ".zip")
    if not prev_zip.is_file():
        return f"（上一版 {best[1].name} 的 zip 已不在 —— 不比较体积）"
    prev_mb = prev_zip.stat().st_size / 1024 / 1024
    return f"（上一版 {best[1].name} {prev_mb:.2f} MB）"


def main() -> int:
    if not PKG.is_dir():
        print("[FAIL] 包目录不存在：", PKG)
        return 1

    files = sorted((p for p in PKG.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(PKG).as_posix())
    if not files:
        print("[FAIL] 包内一个文件都没有 —— 量具没量成，不能当通过")
        return 2

    if ZIP.exists():
        ZIP.unlink()

    # 固定时间戳，让同一份内容两次打包得到同一个字节流（可复现）。
    stamp = (2026, 10, 11, 0, 0, 0)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            rel = p.relative_to(PKG).as_posix()
            info = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())

    raw = ZIP.read_bytes()
    with zipfile.ZipFile(ZIP) as z:
        names = z.namelist()
    dirs = [n for n in names if n.endswith("/")]
    print(f"[OK] 打包 {len(names)} 条目 -> {ZIP}")
    print(f"[OK] 合计 {len(raw)/1024/1024:.2f} MB{_previous_note(BASE, NAME)}")
    print(f"[OK] 目录条目 {len(dirs)} 条（期望 0，与上一版同形）")
    print(f"[OK] sha256 {hashlib.sha256(raw).hexdigest()}")

    if dirs or len(names) != len(files):
        print(f"[FAIL] 条目数 {len(names)} != 文件数 {len(files)}，或存在目录条目")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
