# -*- coding: utf-8 -*-
"""新旧交付包清单对照。

为什么需要它：`_verify_handoff_pack.py` 只回答「我列的那 51 项在不在」。
它对「上一版有、这一版没有」完全沉默 —— 而「该带的没带」正是 2026-10-07
`.mvn` 事故的形态（清单作者没想到的依赖，双向自检都不出声）。
所以这里改成**直接对着旧包求差集**，让量具自己去找，而不是让清单作者去想。

**2026-10-12 修正：判据由「文件大小」改为「内容指纹」。**
原先 `changed` 判定用的是 `stat().st_size` —— **大小相同但内容不同的文件会被判为「未变」**。
这不是假设：第十三轮只改颜色（`#ff2d24` → `#e08a45`，两边都是 7 个字符），
`TrafficWorkbench.vue` 的字节变了、大小没变，于是**它整个从差集里消失了**，
而工具照样打印「内容有变（8）」、exit 0 —— **一个看不见某类变化的量具，
对「它没看见的那一类」给出的是与「真的没变」逐字相同的输出**（M75 家族：
用代理量替代真量；M58 家族：对照构造上问不出差异）。
现改为逐文件 sha256，并配 `--self-test` 造一对「等长不同内容」的样本**证明它咬得住**（M29/M74）。
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, package_dir  # noqa: E402

# 新包路径**从 `_repo.package_dir()` 取**，不写死版本号 —— 写死的那一版在
# 0.9.26 → 0.9.27 时**静默指着一个已不存在的目录**：`manifest()` 对不存在的路径
# 返回空清单，于是每一行都落进「仅旧包有（311）」而「内容有变（0）」——
# 而**「新包一个文件都没有」与「新旧两包完全不同」在报告里长得一样**。
# `_repo.package_dir()` 的 docstring 记着同一处缺陷（0.9.25 → 0.9.26）已经修过一次，
# 只是当时修的是 `_build_handoff_pack.py` 与 `_verify_handoff_pack.py` 两个调用方，
# **本文件自己那一份副本被落下了**。这正是「同一个量两处写死」的又一个实例。
NEW = Path(package_dir())

# 旧包路径**必须由调用者给出**（`python _diff_pack.py <旧包目录>`），因为"上一版"
# 会随每一轮发布前移；把它钉死成某个 `backups/handoff-<日期>/` 路径，下一轮就会
# 静默对着一个过期的参照物比较 —— 而**过期的参照物是本项目点过名的失败模式**
# （见 notes/handoff-packaging.md：「验证独立于被验证对象」）。缺参时报 exit 2
# （无法测量），不报 exit 1（量出来是坏的）：这两者的处置完全不同（M60）。
OLD = (Path(sys.argv[1]) if len(sys.argv) > 1
       else Path(ROOT) / "backups" / "handoff-2026-10-11" / "ALC-交付-0.9.26-beta")


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(root: Path) -> dict:
    """路径 -> (大小, sha256)。**指纹而不是大小**：大小相同的改动必须也算改动。"""
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = (p.stat().st_size, _digest(p))
    return out


def self_test() -> int:
    """造一对**等长但内容不同**的文件，证明差集咬得住（否则本条判据等于没写）。"""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        pa, pb = Path(a) / "x.txt", Path(b) / "x.txt"
        pa.write_bytes(b"#ff2d24\n")
        pb.write_bytes(b"#e08a45\n")   # 同样 8 字节，只有一个字符不同
        if pa.stat().st_size != pb.stat().st_size:
            print("[FAIL] 自检夹具没造出等长样本 —— 本次对照无效")
            return 2
        ma, mb = manifest(Path(a)), manifest(Path(b))
        changed = [k for k in set(ma) & set(mb) if ma[k] != mb[k]]
        if changed != ["x.txt"]:
            print(f"[FAIL] 等长不同内容的样本未被判为有变：{changed}")
            return 2
        # 负向对照：内容真的一样时**不得**报有变（否则判据放宽成了"什么都算变"）
        pc = Path(b) / "y.txt"
        pc.write_bytes(b"#e08a45\n")
        m2 = manifest(Path(b))
        same = [k for k in ("y.txt",) if m2[k] != mb["x.txt"]]
        if same:
            print("[FAIL] 相同内容被判为有变 —— 判据过宽")
            return 2
    print("[OK] self-test：等长不同内容 -> 报有变；相同内容 -> 不报（双向都有牙齿）")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        return self_test()
    if not OLD.exists():
        # 「参照物被回收」是**无法测量**（exit 2），不是**量出来是坏的**（exit 1）。
        # 上一版这里写着 `[FAIL]` —— 而 FAIL 这个词会被读成"包有问题"，
        # 于是读者会去查新包，而新包一直好好的。措辞必须与出口一致（M60）。
        print(f"[CANNOT MEASURE] 参照物（上一版包）已不在：{OLD}")
        print("  用法：python tools/maintenance/_diff_pack.py <上一版包目录>")
        print("  它可能在本轮清理中进了回收站，因此**无法做前后对照**。")
        print("  替代判据：`_build_handoff_pack.py` 的负向/正向自检 + `_verify_zip.py` 的逐条一致。")
        return 2
    old, new = manifest(OLD), manifest(NEW)
    if not old:
        print("[FAIL] 旧包清单为空 —— 量具没量成，不能当通过")
        return 2
    if not new:
        # 与"旧包不在"对称的第三档：**新包不在**时，每一行都会落进「仅旧包有」，
        # 报告看起来像"两包完全不同"，而真相是"新包根本没建出来"。
        # 这是本文件在 0.9.26 → 0.9.27 时真的发生过的失效（NEW 写死了旧版本号）。
        print(f"[CANNOT MEASURE] 新包（本轮交付包）已不在：{NEW}")
        print("  包名随 `VERSION` 走（`_repo.package_dir()`）；先跑 `_build_handoff_pack.py`。")
        return 2

    gone = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])

    print(f"旧包 {len(old)} 文件 / 新包 {len(new)} 文件")
    print(f"仅旧包有（{len(gone)}）:")
    for g in gone:
        print(f"  - {g}")
    print(f"仅新包有（{len(added)}）:")
    for a in added:
        print(f"  + {a}  ({new[a][0]} B)")
    print(f"内容有变（{len(changed)}）:")
    for c in changed:
        flag = "" if old[c][0] != new[c][0] else "   [等长，仅内容变]"
        print(f"  ~ {c}  {old[c][0]} -> {new[c][0]} B{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
