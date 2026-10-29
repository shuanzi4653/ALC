# -*- coding: utf-8 -*-
"""判定 CMA 瓦片路径里的时间约定：UTC 还是北京时。只读。

判据设计（关键）：
  · 若路径用 **UTC**，则存在的最新时次 ≈ now - 发布滞后（约几十分钟）。
  · 若路径用 **北京时**(UTC+8)，则把"北京当下"写成 UTC 格式会落在 **now + 8h 附近**，
    因此存在的最新路径会出现在**未来 8 小时**那一侧。
⇒ 枚举 now-9h .. now+9h 的路径，看 200 出现在哪一侧，即可判定，无需文档。
"""
from __future__ import annotations

import datetime as dt
import ssl
import sys
import urllib.error
import urllib.request

BASE = "https://image.data.cma.cn/tiles/China/RADAR_L3_MST_CREF_GISJPG_Tiles_CR"
STEP = 6
CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (compatible; ALC-radar-probe/1.0)"


def url_for(t):
    return f"{BASE}/{t:%Y%m%d}/{t:%H}/{t:%M}/3/3/6.bin"


def probe(t, retries=2):
    for _ in range(retries):
        try:
            req = urllib.request.Request(url_for(t), headers={"User-Agent": UA}, method="HEAD")
            with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
                return r.status, int(r.headers.get("Content-Length") or 0)
        except urllib.error.HTTPError as e:
            return e.code, 0
        except Exception:
            continue
    return -1, 0


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    base = now.replace(minute=now.minute - (now.minute % STEP))
    print(f"now(UTC) = {base:%Y-%m-%d %H:%MZ}")
    print(f"now(CST) = {base + dt.timedelta(hours=8):%Y-%m-%d %H:%M} 北京时\n")

    hits = []
    for k in range(-90, 91):
        t = base + dt.timedelta(minutes=STEP * k)
        st, ln = probe(t)
        if st == 200:
            hits.append((t, ln))
    if not hits:
        print("RESULT: 无法测量 —— 本机当前也取不到任何时次")
        return 2

    hits.sort()
    newest, oldest = hits[-1][0], hits[0][0]
    print(f"存在时次 {len(hits)} 个，范围 {oldest:%Y-%m-%d %H:%M} .. {newest:%Y-%m-%d %H:%M}（路径字面值）")
    print(f"最新时次相对 now(UTC) 的偏移 = {(newest - base).total_seconds()/3600:+.2f} 小时")
    print("\n窗内 200 的分布（每 30 分钟一格，路径字面值）：")
    buckets = {}
    for t, _ in hits:
        key = t.replace(minute=(t.minute // 30) * 30)
        buckets[key] = buckets.get(key, 0) + 1
    for t in sorted(buckets):
        mark = " <== now(UTC)" if abs((t - base).total_seconds()) < 1800 else ""
        mark += " <== now(北京时,写成UTC)" if abs((t - (base + dt.timedelta(hours=8))).total_seconds()) < 1800 else ""
        print(f"  {t:%m-%d %H:%M}  {buckets[t]:>3}{mark}")

    print("\n== 判定 ==")
    off = (newest - base).total_seconds() / 3600
    if off > 2:
        print(f"  最新时次在 now(UTC) 之后 {off:+.2f} 小时 ⇒ **路径用北京时 (UTC+8)**")
    elif off < -0.15:
        print(f"  最新时次在 now(UTC) 之前 {off:+.2f} 小时 ⇒ **路径用 UTC**，发布滞后约 {-off*60:.0f} 分钟")
    else:
        print(f"  最新时次几乎等于 now(UTC)（{off:+.2f} h）⇒ 路径用 UTC 且几乎无滞后，可疑，需再查")
    return 0


if __name__ == "__main__":
    sys.exit(main())
