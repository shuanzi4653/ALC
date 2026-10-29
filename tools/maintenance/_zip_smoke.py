# -*- coding: utf-8 -*-
"""把 zip 解到临时目录，站**收件人的位置**再验一遍。

为什么不能只验 zip 的条目名：条目名对了、字节坏了（截断/编码坏）在名字上完全看不出来。
所以这里做三件事：
  1. `testzip()` —— CRC 全量核算（能发现坏条目）
  2. 逐条比对解出来的字节与包目录里的字节（sha256 相同）
  3. 在解出来的树上复核启动链路输入 + 凭据是否漏出（换 cwd 重跑，不看原目录）
"""
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import package_dir  # noqa: E402

# 与 `_make_zip.py` / `_verify_zip.py` 同源：包名取自 `VERSION`（见 `_make_zip.py` 顶部说明）。
BASE = Path(os.path.dirname(package_dir()))
NAME = os.path.basename(package_dir())
PKG = BASE / NAME
ZIP = BASE / (NAME + ".zip")
TOP = NAME

MUST_HAVE = [
    "backend-java/mvnw.cmd",
    "backend-java/.mvn/wrapper/maven-wrapper.properties",
    "backend-python/requirements.txt",
    "backend-python/requirements-lock.txt",
    "frontend/package.json",
    "frontend/package-lock.json",
    "scripts/dev.ps1",
    "scripts/start.ps1",
    "config/application.yml",
]
MUST_ABSENT = [
    "config/alc_secret.key",
    "backend-python/data/secrets.db",
    "config/qweather/qweather_private_key.pem",
    "backend-python/_sim_bench.py",
    ".mvn/wrapper/maven-wrapper.properties",  # 反向对照：这条**不该**在顶层
]

FAILS = []


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    with zipfile.ZipFile(ZIP) as z:
        bad = z.testzip()
    if bad:
        print(f"[FAIL] CRC 核算发现坏条目：{bad}")
        return 1
    print("[OK] CRC 全量核算通过（无坏条目）")

    tmp = Path(tempfile.mkdtemp(prefix="alc_zipsmoke_"))
    try:
        with zipfile.ZipFile(ZIP) as z:
            z.extractall(tmp)
        root = tmp / TOP
        if not root.is_dir():
            print(f"[FAIL] 解压后没有 {TOP}/ 这一层，解出来的是：{[p.name for p in tmp.iterdir()][:5]}")
            return 1

        disk_files = {p.relative_to(PKG).as_posix() for p in PKG.rglob("*") if p.is_file()}
        ext_files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        if disk_files != ext_files:
            print(f"[FAIL] 解压后文件集与包目录不同：少 {sorted(disk_files-ext_files)[:5]} 多 {sorted(ext_files-disk_files)[:5]}")
            FAILS.append("fileset")
        else:
            print(f"[OK] 解压后文件集一致（{len(ext_files)} 项）")

        # 字节级抽样：全量比 311 个文件也不贵
        mismatch = [rel for rel in sorted(disk_files & ext_files)
                    if digest(PKG / rel) != digest(root / rel)]
        if mismatch:
            print(f"[FAIL] 字节不一致 {len(mismatch)} 项：{mismatch[:5]}")
            FAILS.append("bytes")
        else:
            print(f"[OK] 字节级一致（{len(disk_files & ext_files)} 项 sha256 全同）")

        lack = [m for m in MUST_HAVE if not (root / m).exists()]
        if lack:
            print(f"[FAIL] 换 cwd 后启动输入缺失：{lack}")
            FAILS.append("must_have")
        else:
            print(f"[OK] 换 cwd 复核：{len(MUST_HAVE)} 项启动输入均在解压树内")

        leaked = [m for m in MUST_ABSENT if (root / m).exists()]
        if leaked:
            print(f"[FAIL] 解压树里出现不该有的路径：{leaked}")
            FAILS.append("must_absent")
        else:
            print(f"[OK] 换 cwd 复核：{len(MUST_ABSENT)} 项排除目标均不存在")

        cred = [p.relative_to(root).as_posix() for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in {".key", ".pem", ".p12", ".pfx", ".jks", ".secret"}]
        if cred:
            print(f"[FAIL] 解压树里仍有密钥类文件：{cred}")
            FAILS.append("cred")
        else:
            print("[OK] 换 cwd 复核：无密钥类文件")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("REGARD:", "FAIL " + ",".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
