# -*- coding: utf-8 -*-
"""0.11.1（Beta）概率层：融合裁决 / 期望损失 / 插值频次表 / 模型卡契约。

这一批用例针对的是**换芯之后新出现的三类静默错误**：

1. **"模型只能更严"被写成"模型可以改松"** —— 后者在演示时完全看不出来：界面照常
   给出"可飞"，只是那一格本该是"注意"。判据因此检查**全网格**上 `fused >= rule`，
   而不是挑几个点看。
2. **频次表在无样本区间插值** —— 插出来的数看起来最正常（它连续、光滑、落在 0–1），
   所以没人会怀疑它；但它不是观测到的频率，是编的。判据要求那一段返回 `None`。
3. **模型卡把两套指标体系并列** —— 0.10.1 的 macroF1（复现判据）与 0.11.1 的
   TS/Brier（预测实测）不可比。判据要求模型卡只带新体系，且四条基线齐备。

另有一条负向验证（坏输入必须给出不可用，而不是一个像样的档位）。
"""
from __future__ import annotations

import json

import pytest

from traffic import v2


# ------------------------------------------------------------ 融合裁决 ----

def test_规则一票否决优先于一切模型概率():
    for p in (0.0, 0.5, 0.79, 0.95):
        level, note = v2._fuse(2, p, 1.0)
        assert level == 2, "规则判关闭时，模型再自信也不能放开"
        assert "一票否决" in note


def test_模型只能更严_全网格():
    """`fused >= rule` 必须在**每一个**格点成立。

    挑点看是测不出来的：漏的那个点是 `(rule=0, p=0.5, conf=0.8)` 这一类边界组合，
    而它在演示里恰好不出现。
    """
    for rule in (0, 1, 2):
        for p in [i / 20 for i in range(21)]:
            for conf in [0.0, 0.2, 0.6499, 0.65, 0.8, 1.0]:
                fused, _ = v2._fuse(rule, p, conf)
                assert fused >= rule, f"rule={rule} p={p} conf={conf} 竟然被放松了"


def test_低置信一律转人工_不给结论():
    level, note = v2._fuse(0, 0.99, 0.6499)
    assert level == 0 and "人工" in note, "置信度不足时不能升档，要交给人"
    level, note = v2._fuse(0, 0.99, 0.65)
    assert level == 1, "恰好等于门限应当参与裁决（后端是 `<0.65` 才转人工）"


def test_概率升档的两条线不互相覆盖():
    """两段阈值的关系固定，**具体数值不许写进判据**。

    0.11.16 修：这里原来硬写着 0.80 / 0.50 —— 而 0.11.15 的 K-1 已经把阈值改成
    0.25 / 0.15。于是这一条从 0.11.15 起**一直是红的**，只是那一轮的「后端判据
    13/13」只统计了 H 系列，没跑全量套件（M95：判据的期望值是易腐品；设计改过
    之后它会持续把"正确"报成"失败"，而且看起来像回归）。

    现在判据只钉**结构**：`watch < block`、两段各给一条不同的说明、档位不越界。
    阈值本身由 `test_概率阈值必须落在模型自己的工作点附近` 与
    `tools/maintenance/_probe_0116_prob_tier.py` 负责，各管一件事。
    """
    block, watch = v2.P_PROB_BLOCK, v2.P_PROB_WATCH
    assert 0.0 < watch < block <= 1.0, "两段阈值必须有序且在 (0,1] 内"
    assert v2._fuse(0, block, 1.0) == (1, "模型升级为观察（待人工确认）")
    assert v2._fuse(0, (block + watch) / 2, 1.0) == (1, "模型提示风险，升为注意")
    assert v2._fuse(0, round(watch - 0.01, 4), 1.0) == (0, "规则优先")
    # 已经是 1 的时候，watch 那一段不该再"升"一次（档位只有三档，没有 1.5）
    assert v2._fuse(1, min(1.0, block + 0.2), 1.0)[0] == 1


def test_消融关掉概率层之后概率分支必须不再生效():
    """负向对照（M58）。

    `ablate=prob` 的意思是"这一轮概率层不参与"。0.11.15 之前它只关掉了
    `prob_change`，`_fuse()` 的两条概率分支照样改判 —— 于是消融表里那一行的
    `divergedProbability` 仍是 626，"去掉概率层"这一列看起来有内容，
    读者会得出"概率层没用"这个**方向相反**的结论。
    """
    block, watch = v2.P_PROB_BLOCK, v2.P_PROB_WATCH
    assert v2._fuse(0, block, 1.0, use_probability=False) == (0, '本轮为消融实验：概率层未参与')
    assert v2._fuse(0, (block + watch) / 2, 1.0, use_probability=False)[0] == 0
    # 规则一票否决不受消融影响：安全硬约束不是"模型的一部分"。
    assert v2._fuse(2, block, 1.0, use_probability=False)[0] == 2
    # 默认行为不变（不传就是完整系统）。
    assert v2._fuse(0, block, 1.0)[0] == 1


# ------------------------------------------------------------ 期望损失 ----

def test_期望损失选最小且可解释():
    params = v2.LOSS_PARAMS["balanced"]
    low = v2._decision(0.02, None, None, params)
    assert low["chosen"] == "DIRECT", "低概率时直飞应当最省"
    assert "CANCEL" in low["excluded"], "取消必须被显式排除并说明原因"
    high = v2._decision(0.99, None, 0.1, params)
    assert high["chosen"] == "REROUTE", "有可用备选走廊时，绕飞应当胜过取消与直飞"
    assert set(low["losses"]) == {"DIRECT", "DELAY", "REROUTE", "CANCEL"}, "四项损失都要算出来，供评委逐项核对"
    assert low["losses"]["CANCEL"] == params["cancel"]


def test_取消只在没有可执行动作时才允许():
    """`c_cancel=180` 比 `25 + 0.83×10000` 小得多，纯按 argmin 会一路推出"取消最优"。

    这条钉住的是那层**可行性**判断：能绕飞就绕飞，绕不了才在延误与取消之间比。
    """
    params = v2.LOSS_PARAMS["balanced"]
    reroute = v2._decision(0.83, None, 0.12, params)
    assert "CANCEL" not in reroute["eligible"], "有备选走廊时不允许取消"
    assert reroute["losses"]["CANCEL"] < reroute["losses"]["REROUTE"], (
        "反例自检：按纯成本，取消确实更便宜 —— 正因如此才需要可行性门限")
    # 备选走廊也不可用时，取消才回到候选集
    blocked = v2._decision(0.83, None, 0.95, params)
    assert "CANCEL" in blocked["eligible"] and "REROUTE" not in blocked["eligible"]
    assert blocked["chosen"] in ("DELAY", "CANCEL")
    # 概率没到"需谨慎"线时，取消连选项都不是
    mild = v2._decision(0.10, None, None, params)
    assert "CANCEL" not in mild["eligible"]


def test_三档风险偏好必须真的不同():
    """保守档的事故代价更高 ⇒ 在同一个概率上更早放弃直飞。

    取 p=0.50 / 备选 0.497（差 0.003）：绕飞胜出的条件是 `p - p_alt > 25 / I`，
    这个门槛随 I 变化 —— 保守档 0.00125、均衡档 0.0025、效率档 0.00625。
    于是同一个情形下保守与均衡选绕飞、效率选直飞。如果三档只改了名字没改参数，
    这一条会红，而界面上"保守/均衡/效率"三个按钮看起来都正常、点下去结果一样。
    """
    pick = {name: v2._decision(0.50, None, 0.497, params)["chosen"]
            for name, params in v2.LOSS_PARAMS.items()}
    assert pick["conservative"] == "REROUTE"
    assert pick["balanced"] == "REROUTE"
    assert pick["efficiency"] == "DIRECT", "效率档在同样的风险缺口上应当仍选直飞"
    incident = [v2.LOSS_PARAMS[k]["incident"] for k in ("conservative", "balanced", "efficiency")]
    assert incident == sorted(incident, reverse=True), "事故代价必须随偏好单调"


# ------------------------------------------------------ 概率频次表（延伸段）----

def test_频次表右开区间且无样本段不给数():
    table = {"bins": [0, 1000, 3000, 24000], "freq": [0.5, None, 0.01]}
    assert v2._table_prob(table, "vis", 0) == 0.5
    assert v2._table_prob(table, "vis", 999) == 0.5
    assert v2._table_prob(table, "vis", 1000) is None, "第二箱没有样本 ⇒ 不给数，不插值"
    assert v2._table_prob(table, "vis", 5000) == 0.01
    assert v2._table_prob(table, "vis", 24000) is None, "超出末箱边界不给数"
    assert v2._table_prob(None, "vis", 1000) is None
    assert v2._table_prob(table, "vis", None) is None


# ---------------------------------------------------------------- 模型卡 ----

@pytest.fixture(scope="module")
def card():
    payload = v2.modelcard()
    if payload.get("status") != "OK":
        pytest.skip("模型卡载荷未生成：先跑 tools/ml/train_nowcast.py")
    return payload


def test_模型卡三任务与四条基線齐备(card):
    keys = [t["key"] for t in card["tasks"]]
    assert keys == ["vis3k", "vis", "gust"]
    for key in keys:
        target = card["targets"][key]
        for base in ("persistence", "openMeteo", "thresholdRule"):
            assert base in target["baselines"], f"{key} 缺基线 {base}"
        for metric in ("TS", "POD", "FAR", "Brier"):
            assert metric in target["model"], f"{key} 缺指标 {metric}"
        assert target["model"]["operatingThreshold"] is not None, "工作点阈值必须随指标一起发布"


def test_模型卡不含旧指标体系(card):
    """macroF1 是"复现判据"的指标。它一旦出现在本卡里，读者会把两套数并列比较。"""
    text = json.dumps(card, ensure_ascii=False)
    assert "macroF1" not in text
    assert "labels-v1" not in text


def test_失败样本来自测试集(card):
    """训练集上的错例没有信息量 —— 模型见过它。"""
    for target in card["targets"].values():
        for row in target.get("failures") or []:
            assert str(row["timeUtc"]) >= "2025-01-01", f"失败样本落在 test 之前：{row['timeUtc']}"


def test_内存里的模型版本与指标文件一致(card):
    version = card.get("version")
    assert version, "指标文件必须带版本号，否则无法与 kernel 对账"
    for key, name in (card.get("loaded") or {}).items():
        assert name, f"{key} 没有加载到模型"
        assert name.startswith("ml-%s" % version), f"{key} 加载的是 {name}，与指标文件 {version} 不一致"


def test_导出对照必须通过(card):
    for key, target in card["targets"].items():
        parity = target.get("exportParity") or {}
        if not parity:
            continue
        assert parity["maxAbsDiff"] <= parity["tolerance"], (
            f"{key} 导出与 sklearn 偏差 {parity['maxAbsDiff']} 超过容差 {parity['tolerance']}")


# ------------------------------------------------- K-9 / K-10（0.11.16）----

def test_K9_能见度下界必须跟着数一起走():
    """`6+` 换算成 9656 m 是**下界**，不是一次精确观测。

    判据那一侧（`_criteria`）从 0.11.1 起就带 `display` / `lowerBound`；
    走廊行与详情却只带 `visM`，于是同一屏上判据说「≥ 9656 m」、走廊说「9656 m」。
    这里钉住两条出口都带标记，且缺测时标记为 False（不是"下界 0 米"）。
    """
    observed = {"visM": 9656.0, "gustMs": 4.0, "cloudBaseM": 5000.0,
                "visLowerBound": True, "visRaw": "6+"}
    payload = {"stations": [{"station": "ZYTX", "available": True,
                             "observedAt": "2026-10-23T08:00:00Z", "observed": observed}]}
    row = v2._criteria(payload, (0.0, 0.0))[0]
    assert row["lowerBound"] is True
    # 9656 m ≥ 1000 m ⇒ 用 km 印（与 `_vis_display` 一致），但下界标记必须在句首。
    assert row["display"].startswith("≥ 9.7 km"), row["display"]
    assert "6+" in row["display"]
    # 同一个来源：走廊能见度也要带下来（否则走廊那一格仍在印"恰好"）。
    visibility = v2._idw_visibility(0.0, 0.0, payload)
    assert visibility["visLowerBound"] is True
    assert visibility["visRaw"] == "6+"
    # 缺测：标记为 False，且值仍是 None —— 不是"0 米，下界"。
    empty = v2._idw_visibility(0.0, 0.0, {"stations": []})
    assert empty["visLowerBound"] is False and empty["visM"] is None


def test_K10_模型卡版本与阈值读唯一来源(card):
    """版本号不能写死，训练阈值与运行阈值必须并排给出。

    两个世界各有一次事故：标题写死 `0.11.1`（读者不知道这页说的是哪一代系统），
    以及阈值只印"运行期那个"（模型按 10 m/s 打标签，改了配置没有任何数字会红）。
    """
    from pathlib import Path

    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    assert card.get("systemVersion") == version_file.read_text(encoding="utf-8").strip()
    assert card["systemVersion"] != "0.11.1", "标题不许再写死指标体系起点"

    thresholds = card.get("gustThreshold") or {}
    assert thresholds.get("training") == card["targets"]["gust"]["threshold"]
    assert thresholds.get("runtime") is not None
    assert thresholds.get("consistent") is True, "配置阈值与训练阈值分叉，模型在答另一个问题"


def test_K10_阈值分叉必须被自己看见(card, monkeypatch):
    """负向对照（M58）：把运行阈值拨开一点，`consistent` 必须立刻翻假。

    没有这一条，"两者一致"就只是一句**永远不会为假**的话 —— 而这句话正是
    卡片存在的理由（改了配置那一侧、没人会去看模型卡，症状是"模型好像变差了"）。
    """
    from traffic import v2 as module

    monkeypatch.setattr(module.nowcast, "GUST_LIMIT_MS", float(card["gustThreshold"]["runtime"]) + 1.5)
    drifted = module.modelcard()
    assert drifted["gustThreshold"]["consistent"] is False
    assert drifted["gustThreshold"]["runtime"] != card["gustThreshold"]["runtime"]


# ---------------------------------------------------------------- 判据清单 ----

def test_判据缺值时是_无法判定_而不是_不满足():
    """`passed=None` 与 `passed=False` 在界面上必须长得不一样。

    `Number(null)===0` 那一类错误的变体：把"没取到"读成"取到了 0 米能见度"，
    于是每一座没报云底的机场都被判成"不满足"。
    """
    payload = {"stations": [{"station": "ZYTX", "available": True, "observedAt": "2026-10-18T22:00:00Z",
                             "observed": {"visM": 8000.0, "gustMs": None, "cloudBaseM": None}}]}
    rows = v2._criteria(payload, (0.0, 0.0))
    by_metric = {r["metric"]: r for r in rows}
    assert by_metric["能见度"]["passed"] is True
    assert by_metric["阵风"]["passed"] is None, "阵风缺测 ⇒ 无法判定"
    assert by_metric["云底高"]["passed"] is None, "云底缺测 ⇒ 无法判定"
    for row in rows:
        assert row["source"].startswith("METAR "), "来源必须写清是哪个站的实测"


# -------------------------------------------------------------- 分歧台账 ----

def test_台账读写往返_空台账如实说空(tmp_path, monkeypatch):
    monkeypatch.setattr(v2, "DECISION_DIR", tmp_path)
    empty = v2.divergences()
    assert empty["status"] == "OK" and empty["empty"] is True and empty["rows"] == []
    assert empty["note"], "空台账必须说明为什么空，而不是只给一个空数组"

    saved = v2.record_decision({"corridorId": "1-07", "p": 0.62, "confidence": 0.24,
                                "verdict": "REJECT", "note": "实测能见度 4 km，模型偏保守"})
    assert saved["status"] == "OK"
    rows = v2.divergences()["rows"]
    assert len(rows) == 1
    assert rows[0]["corridorId"] == "1-07"
    assert rows[0]["verdict"] == "REJECT"
    assert rows[0]["note"], "理由必须落盘 —— 台账的价值全在这一列"
    assert rows[0]["rolledBack"] is False


def test_台账按最新在前(tmp_path, monkeypatch):
    monkeypatch.setattr(v2, "DECISION_DIR", tmp_path)
    for i in range(3):
        v2.record_decision({"corridorId": "1-0%d" % i, "verdict": "ACCEPT", "note": "n%d" % i})
    rows = v2.divergences()["rows"]
    assert [r["corridorId"] for r in rows] == ["1-02", "1-01", "1-00"]


# ------------------------------------------------------- 走廊载荷的自洽性 ----

def test_走廊里出现的概率必须能对上档位词():
    payload = v2.corridors(limit=5)
    if payload.get("status") != "OK" or not payload.get("items"):
        pytest.skip("三站观测当前不可用（这是真实状态，不是测试失败）")
    for row in payload["items"]:
        p = row["pMax"]
        # 0.11.17：阈值**不许写死**。原来这里写 0.8 / 0.5，而判定层从 0.11.15 起
        # 读 `P_PROB_BLOCK/WATCH`（现在更进一步来自 config::probability）——
        # 于是这条判据在阈值下调后一直红着，看起来像"判定坏了"（M95）。
        expected = ("不可飞" if p >= v2.P_PROB_BLOCK
                    else "需谨慎" if p >= v2.P_PROB_WATCH else "可飞")
        assert row["verdict"] == expected, f"{row['corridorId']} 概率 {p} 与档位 {row['verdict']} 不一致"
        assert row["confidence"] in ("OK", "LOW")
        assert 0.0 <= p <= 1.0
        # 原来的断言是 `>= SIGMA_BASE`（0.05）。那是**旧线性公式的截距**
        # （`σ = 0.05 + 0.02 × 站距`），W-08 换成 LOOCV 之后它只剩"可追溯"用途。
        # LOOCV 的残差在"三站读数几乎一致"时会趋近 0，`_loocv_sigma` 明确允许
        # 下探到 `SIGMA_FLOOR`（0.02）—— 晴天三站都说能见度 20 km，σ 就该很小，
        # 那不是"过度自信"，那是它们真的没有分歧。
        # 真正的不变量是**区间**：不写出比下限更小的数，也不越过上限（越过说明
        # 三站分歧已大到不该给概率，必须由 `confidence` 降级）。
        assert v2.SIGMA_FLOOR <= row["sigmaMean"] <= v2.SIGMA_CAP, (
            f"{row['corridorId']} 的 σ {row['sigmaMean']} 越出 [{v2.SIGMA_FLOOR}, {v2.SIGMA_CAP}]")


def test_translator_model_branch_does_not_raise_name_error():
    """有 Key 才走的分支必须能被走到。

    2026-10-19 线上实测：`v2.py` 用了 `httpx` 但没 import，本机因为没有 Key
    在更早的分支就 return 了，所以**本地全绿、云端炸 NameError** —— 界面上表现为
    "生成一句解读"永远返回模板，而模板本身看起来完全正常（那才是最坏的地方）。
    这里用一个假 Key 强制走模型分支：预期是网络类失败，**不允许出现 NameError**。
    """
    from traffic import v2
    result = v2.translator('CAR-2-01-3-01', {'api_key': 'sk-invalid',
                                             'base_url': 'http://127.0.0.1:9',
                                             'model': 'deepseek-chat'})
    assert result['status'] == 'OK'
    assert 'NameError' not in (result.get('note') or ''), result.get('note')
    assert result['source'] in ('TEMPLATE', 'MODEL')
    assert result['text'], '降级也必须给出一句可读的句子'
