# -*- coding: utf-8 -*-
"""只读取证：中央气象台(NMC) 组合反射率拼图 PNG 的可获得性与配色分档。

退出码：
  0 = 取到样张并完成分析
  1 = 取到样张但分析失败
  2 = 一个时次都取不到（无法测量）
本探针不 import backend-python 的任何业务模块，也不写任何业务文件。
"""
from __future__ import annotations

import hashlib
import io
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

OUT = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"
HOST = "https://image.nmc.cn"
PRODUCT = "RDCP"
SIZES = ("medium", "small")
UA = "Mozilla/5.0 (compatible; ALC-radar-probe/1.0)"

CTX = ssl.create_default_context()


def url_for(dt: datetime, size: str) -> str:
    ts = dt.strftime("%Y%m%d%H%M%S") + "000"
    return (
        f"{HOST}/product/{dt:%Y/%m/%d}/{PRODUCT}/{size}/"
        f"SEVP_AOC_RDCP_SLDAS3_ECREF_ACHN_L88_PI_{ts}.PNG"
    )


def fetch(url: str, retries: int = 3):
    """返回 (status, bytes, ctype, elapsed)。网络抖动重试，HTTP 错误不重试。"""
    last = None
    for i in range(retries):
        t0 = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return r.status, r.read(), r.headers.get("Content-Type"), time.time() - t0
        except urllib.error.HTTPError as e:
            return e.code, b"", e.headers.get("Content-Type"), time.time() - t0
        except Exception as e:  # 传输层抖动
            last = e
            time.sleep(0.6 * (i + 1))
    return -1, repr(last).encode(), None, 0.0


LAG_MIN = 12  # 产品发布延迟：整点过后一般需十余分钟才落盘
SWEEP = 24    # 往回扫多少个网格点（24 × 6min = 144 min）


def candidates():
    """对齐 6 分钟发布网格（分钟为 6 的整数倍）后回溯枚举候选时次。

    关键：NMC 只在整 6 分钟时次发布，形如 now-6n 的"自由步长"会全部落在
    非网格点上而一律 404 —— 那看起来像"源下线"，实际是枚举方式错了。
    """
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    base_minute = now.minute - (now.minute % 6)
    base = now.replace(minute=base_minute) - timedelta(minutes=LAG_MIN)
    return [base - timedelta(minutes=6 * i) for i in range(SWEEP)]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    print(f"== 1) 时次探测（medium，6 分钟网格，延迟 {LAG_MIN} min，回扫 {SWEEP} 点） ==")
    found = []
    hits = 0
    for dt in candidates():
        u = url_for(dt, "medium")
        st, body, ctype, el = fetch(u)
        flag = ""
        if st == 200 and len(body) > 1000:
            hits += 1
            found.append((dt, u, body))
            flag = "  <== OK"
        print(f"  {dt:%Y-%m-%d %H:%MZ}  HTTP {st}  {len(body):>8} B  {ctype}  {el:.2f}s{flag}")
        if hits >= 3:
            break
    if not found:
        print("RESULT: 无法测量 —— 所有候选时次均不可得")
        return 2

    newest_dt, newest_url, blob = found[0]
    path = os.path.join(OUT, f"nmc_{newest_dt:%Y%m%d%H%M}.PNG")
    with open(path, "wb") as fh:
        fh.write(blob)
    print(f"\n== 2) 样张落盘 ==\n  {path}\n  {len(blob)} B  sha256={hashlib.sha256(blob).hexdigest()[:16]}")
    print(f"  url={newest_url}")

    print("\n== 3) 尺寸与配色 ==")
    try:
        from PIL import Image  # noqa: PLC0415
    except Exception as e:
        print(f"  PIL 不可用：{e}")
        print("RESULT: 取得样张但无法在此解释器中分析")
        return 1

    im = Image.open(io.BytesIO(blob))
    print(f"  mode={im.mode} size={im.size} format={im.format}")
    print(f"  info keys={sorted(im.info.keys())}")
    rgba = im.convert("RGBA")
    px = list(rgba.getdata())
    print(f"  pixels={len(px)}")

    opaque = [p for p in px if p[3] > 0]
    print(f"  opaque={len(opaque)} ({len(opaque)/max(1,len(px))*100:.2f}%)")
    print(f"  fully_transparent={len(px)-len(opaque)}")

    cnt = Counter(opaque)
    print(f"  distinct_opaque_colors={len(cnt)}")
    print("  top-30 colors (RGBA, count, share-of-opaque):")
    for c, n in cnt.most_common(30):
        rgba_hex = "#%02x%02x%02x" % c[:3]
        print(f"    {rgba_hex} a={c[3]:<3} {n:>9}  {n/max(1,len(opaque))*100:6.3f}%")

    # 是否有 alpha 半透明档（等值面常见的分层）
    alphas = Counter(p[3] for p in opaque)
    print(f"  alpha levels={len(alphas)} top={alphas.most_common(6)}")

    print("\n== 4) small 尺寸对照 ==")
    st, body2, ctype2, el2 = fetch(url_for(newest_dt, "small"))
    if st == 200:
        im2 = Image.open(io.BytesIO(body2))
        print(f"  small: HTTP {st} {len(body2)} B size={im2.size} mode={im2.mode} ({el2:.2f}s)")
    else:
        print(f"  small: HTTP {st}")

    print("\nRESULT: 取得样张并完成分析")
    return 0


if __name__ == "__main__":
    sys.exit(main())
