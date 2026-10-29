"""跨语言规则一致性测试（C02）。

直接消费与 Java `SfiRuleCasesTest` **同一份** `tests/fixtures/rule-cases.json`，
断言 Python 侧 rules.evaluate 的 rawSfi / sfi / level / hardBan / penalty 与之完全一致。
任何一端偏离配置都会让对应语言测试失败。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rules  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "rule-cases.json"


def load_fixture():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return json.load(f)


def test_fixture_exists_and_loads():
    assert FIXTURE.is_file(), "缺少跨语言规则用例夹具：%s" % FIXTURE
    data = load_fixture()
    assert data["cases"], "用例集为空"
    assert data["ruleVersion"] == "v1"


def test_golden_cases_match_configured_rules():
    spec = rules.load_spec()
    assert spec.source.endswith("rules-v1.json"), "未从配置文件加载规则：%s" % spec.source

    checked = 0
    for case in load_fixture()["cases"]:
        snapshot = dict(case["snapshot"])
        expect = case["expect"]
        result = rules.evaluate(snapshot, spec)
        case_id = case["id"]

        if "rawSfi" in expect:
            assert result["raw_sfi"] == expect["rawSfi"], "[%s] raw_sfi" % case_id
        if "sfi" in expect:
            assert result["sfi"] == expect["sfi"], "[%s] sfi" % case_id
        if "level" in expect:
            assert result["level"] == expect["level"], "[%s] level" % case_id
        if "hardBan" in expect:
            assert result["hard_ban"] == expect["hardBan"], "[%s] hard_ban" % case_id
        if "penalty" in expect:
            assert result["penalty"] == expect["penalty"], "[%s] penalty" % case_id
        checked += 1

    assert checked == len(load_fixture()["cases"])


def test_invalid_cases_are_rejected():
    spec = rules.load_spec()
    checked = 0
    for case in load_fixture()["invalidCases"]:
        with pytest.raises(ValueError):
            rules.evaluate(dict(case["snapshot"]), spec)
        checked += 1
    assert checked == len(load_fixture()["invalidCases"])


def test_absent_optional_factor_abstains_instead_of_failing():
    """真实源形状：open-meteo 不发布雷暴字段，thunderProb 恒为 None，其余齐全。

    回归判据（0.9.25）：修复前这会抛 ValueError，与 Java 侧同因，
    使监测轮永久以 INVALID_INPUT 失败、/api/health/ready 恒为 503。
    """
    spec = rules.load_spec()
    snapshot = {"windSpeed": 2.27, "windGust": 4.6, "precipMmh": 0.0,
                "visibilityM": 8760.0, "thunderProb": None, "tempC": 15.6}
    result = rules.evaluate(snapshot, spec)
    assert result["hard_ban"] is False
    # 缺席的可选要素不产出 check（扣不了分），但要被点名，界面才能如实说「源不提供」。
    assert all(c["factor"] != "雷暴概率" for c in result["checks"])
    assert result["unavailable_optional"] == ["雷暴概率"]
    assert any(c["factor"] == "平均风速" for c in result["checks"])


def test_absent_required_factor_still_rejects_the_round():
    """必需要素缺席＝本该有却没有，本轮不可信——不能被上一条放松。"""
    spec = rules.load_spec()
    with pytest.raises(ValueError):
        rules.evaluate({"windSpeed": None, "windGust": 5, "precipMmh": 0,
                        "visibilityM": 20000, "thunderProb": 0, "tempC": 20}, spec)


def test_optional_factor_still_scores_when_present():
    """可选要素一旦取得值，就必须照常参与计分——弃权只针对缺席，不是永久豁免。"""
    spec = rules.load_spec()
    result = rules.evaluate({"windSpeed": 2.0, "windGust": 4.0, "precipMmh": 0.0,
                             "visibilityM": 20000.0, "thunderProb": 0.7, "tempC": 20.0}, spec)
    assert any(c["factor"] == "雷暴概率" and c["banned"] for c in result["checks"])
    assert result["hard_ban"] is True


def test_fallback_output_contract():
    """降级研判输出必须带 source=fallback 的语义字段，且等级与规则一致。"""
    from track2_agent import _fallback

    result = _fallback(
        {"windSpeed": 12, "windGust": 5, "precipMmh": 0, "visibilityM": 20000,
         "thunderProb": 0, "tempC": 20},
        hours=6, region="演示作业区-01", task_type="巡检")

    assert result["risk_level"] == "禁飞"
    assert result["hard_ban"] is True
    assert result["sfi"] == 39
    assert result["raw_sfi"] == 60
    assert result["rule_version"] == "v1"
    assert result["advice"]
    assert result["alert_text"].startswith("【低空飞行气象通报】")


def test_fallback_rejects_missing_fields():
    from track2_agent import _fallback

    with pytest.raises(ValueError):
        _fallback({"windGust": 5, "precipMmh": 0, "visibilityM": 20000,
                   "thunderProb": 0, "tempC": 20},
                  hours=6, region="演示作业区-01", task_type="巡检")


def test_fallback_accepts_yunqi_nested_structure():
    """兼容和风原始嵌套结构（不因字段形态不同而误判）。"""
    from track2_agent import _fallback

    nested = {
        "wind": {"speed": {"value": 4.0}},
        "windGust": {"value": 5.8},
        "precipitation": {"intensity": {"value": 0.0}},
        "visibility": {"value": 21000},
        "thunderProb": 0.0,
        "tempC": 19.0,
    }
    result = _fallback(nested, hours=6, region="演示作业区-01", task_type="巡检")
    assert result["risk_level"] == "适飞"
    assert result["raw_sfi"] == 100
