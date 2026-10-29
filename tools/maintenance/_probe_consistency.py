"""线上 5 页数据一致性巡检（只读，不写任何东西）。

判据不是"接口 200"，而是**同一件事在不同接口里说的是不是同一句话**。
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

BASE = "https://tianchuang.shuanzi.site"
HDR = {"X-ALC-Workspace": "probe-consistency-1021"}


def get(path: str, timeout: int = 30):
    req = urllib.request.Request(BASE + path, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw.strip().startswith(("{", "[")) else raw
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, body[:300]


def head(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    head("1. overview")
    st, ov = get("/api/traffic/v2/overview")
    print("status", st)
    if st == 200:
        print("planId     ", ov.get("planId"))
        print("scenario   ", ov.get("scenario"), ov.get("scenarioLabel"))
        print("timeBase   ", ov.get("timeBase"))
        print("conclusion ", (ov.get("conclusion") or {}).get("text"))
        for k in ov.get("kpis") or []:
            print(f"  kpi {k['key']:<9} {k['value']} {k['unit']:<3} | {k['label']} | {k['baseline']}")
        c = ov.get("corridors") or {}
        print("corridors  total=%s high=%s watch=%s" % (c.get("total"), c.get("high"), c.get("watch")))

    head("2. corridors 全量")
    st, co = get("/api/traffic/v2/corridors?limit=60")
    print("status", st)
    if st == 200:
        rows = co.get("items") or []
        print("total=", co.get("total"), "returned=", co.get("returned"), "len(items)=", len(rows))
        # 走廊档位与 verdict 是否同源
        bad = [r for r in rows if r.get("verdict") == "可飞" and float(r.get("pMax") or 0) >= 0.5]
        print("verdict=可飞 但 pMax≥0.5 的条数 =", len(bad))
        for r in rows[:3]:
            print("  ", r.get("corridorId"), r.get("verdict"), r.get("pMax"), r.get("visLevel"))
        stamps = {(co.get("observation") or {}).get("observedAt")}
        per = {(s.get("station"), s.get("observedAt")) for s in (co.get("observation") or {}).get("stations") or []}
        print("帧时刻 =", stamps, " 逐站 =", sorted(per))

    head("3. counterfactual（实时）")
    st, cf = get("/api/traffic/v2/counterfactual")
    print("status", st)
    if st == 200:
        for key in ("a", "b", "summary", "exposureA", "exposureB", "diverged"):
            if key in cf:
                print(f"  {key} = {json.dumps(cf[key], ensure_ascii=False)[:220]}")
        print("  keys:", sorted(cf.keys()))

    head("4. alerts（实时）")
    st, al = get("/api/traffic/v2/events")
    print("status", st)
    if st == 200:
        print("  keys:", sorted(al.keys()))
        groups = al.get("items") or al.get("groups") or []
        print("  groups =", len(groups), " total =", al.get("total"))
        for g in groups[:5]:
            print("   ", {k: g.get(k) for k in ("key", "short", "weather", "count", "closedCount") if k in g})

    head("5. 案例页 ?case=fog-20250105 四接口时刻是否同源")
    for path in (
        "/api/traffic/v2/overview?case=fog-20250105",
        "/api/traffic/v2/corridors?limit=5&case=fog-20250105",
        "/api/traffic/v2/counterfactual?case=fog-20250105",
        "/api/traffic/v2/alerts?case=fog-20250105",
    ):
        st, data = get(path)
        if st != 200:
            print(f"  {path} -> {st} {str(data)[:120]}")
            continue
        stamp = (
            (data.get("observation") or {}).get("observedAt")
            or data.get("observedAt")
            or data.get("timeBase")
            or (data.get("case") or {}).get("timeBase")
        )
        print(f"  {path.split('?')[1][:46]:<48} -> {stamp}")


if __name__ == "__main__":
    main()
