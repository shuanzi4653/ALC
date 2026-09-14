"""轨1 规则的 Python 实现（C02）。

与 Java 侧 `SfiEngine` **读取同一份配置** `config/rules-v1.json`，并实现相同的比较符语义，
使两端在任何输入下得到一致的 rawSfi / sfi / level / hardBan。`tests/fixtures/rule-cases.json`
作为跨语言 golden cases 同时被两端断言，任何一侧偏离都会立即失败。

比较符语义（与 Java 完全一致）：
    direction=high ：v >= banValue 禁飞；v >= warnValue 警戒
    direction=low  ：v <= banValue 禁飞；v <= warnValue 警戒
    direction=range：v < banLow 或 v > banHigh 禁飞；v < warnLow 或 v > warnHigh 警戒
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = APP_ROOT / "config" / "rules-v1.json"

LEVEL_LABELS_CN = {"FIT": "适飞", "CAUTION": "谨慎", "DANGER": "危险", "BAN": "禁飞"}

# 有效范围（与 Java ObservationValidator 一致）：缺失、非有限或越界一律判为不可用，
# 不得默认成安全值。温度允许负值，不能套用非负校验。
RANGE_LIMITS = {
    "windSpeed": (0.0, 150.0),
    "windGust": (0.0, 200.0),
    "precipMmh": (0.0, 500.0),
    "visibilityM": (0.0, 100_000.0),
    "thunderProb": (0.0, 1.0),
    "tempC": (-100.0, 70.0),
}

# 与 Java RuleSpec.defaultFactors() 等价的内置兜底（配置缺失时使用）
_DEFAULT_FACTORS: List[Dict[str, Any]] = [
    {"key": "windSpeed", "label": "平均风速", "unit": "m/s", "direction": "high",
     "warnValue": 8, "banValue": 12, "penaltyWarn": 22, "penaltyBan": 40,
     "noteOk": "正常", "noteWarn": "超适飞阈值", "noteBan": "达禁飞阈值"},
    {"key": "windGust", "label": "阵风风速", "unit": "m/s", "direction": "high",
     "warnValue": 12, "banValue": 18, "penaltyWarn": 16, "penaltyBan": 30,
     "noteOk": "正常", "noteWarn": "超适飞阈值", "noteBan": "达禁飞阈值"},
    {"key": "precipMmh", "label": "降水强度", "unit": "mm/h", "direction": "high",
     "warnValue": 1, "banValue": 5, "penaltyWarn": 15, "penaltyBan": 35,
     "noteOk": "无降水", "noteWarn": "出现降水", "noteBan": "达禁飞阈值"},
    {"key": "visibilityM", "label": "能见度", "unit": "km", "direction": "low",
     "warnValue": 5000, "banValue": 1000, "penaltyWarn": 12, "penaltyBan": 30,
     "displayDivisor": 1000, "noteOk": "良好", "noteWarn": "偏低", "noteBan": "低于禁飞阈值"},
    {"key": "thunderProb", "label": "雷暴概率", "unit": "%", "direction": "high",
     "warnValue": 0.2, "banValue": 0.6, "penaltyWarn": 12, "penaltyBan": 35,
     "displayMultiplier": 100, "noteOk": "低", "noteWarn": "存在风险", "noteBan": "过高"},
    {"key": "tempC", "label": "温度", "unit": "℃", "direction": "range",
     "warnLow": -10, "warnHigh": 40, "banLow": -20, "banHigh": 45,
     "penaltyWarn": 10, "penaltyBan": 30,
     "noteOk": "正常", "noteWarn": "接近边界", "noteBan": "超出安全范围"},
]


@dataclass
class FactorRule:
    key: str
    label: str
    unit: str
    direction: str = "high"
    warnValue: Optional[float] = None
    banValue: Optional[float] = None
    warnLow: Optional[float] = None
    warnHigh: Optional[float] = None
    banLow: Optional[float] = None
    banHigh: Optional[float] = None
    penaltyWarn: int = 0
    penaltyBan: int = 0
    displayDivisor: float = 1.0
    displayMultiplier: float = 1.0
    noteOk: str = "正常"
    noteWarn: str = "警戒"
    noteBan: str = "达禁飞阈值"

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "FactorRule":
        divisor = raw.get("displayDivisor") or 1.0
        multiplier = raw.get("displayMultiplier") or 1.0
        return cls(
            key=str(raw.get("key", "")),
            label=str(raw.get("label", raw.get("key", ""))),
            unit=str(raw.get("unit", "")),
            direction=(raw.get("direction") or "high"),
            warnValue=raw.get("warnValue"),
            banValue=raw.get("banValue"),
            warnLow=raw.get("warnLow"),
            warnHigh=raw.get("warnHigh"),
            banLow=raw.get("banLow"),
            banHigh=raw.get("banHigh"),
            penaltyWarn=int(raw.get("penaltyWarn") or 0),
            penaltyBan=int(raw.get("penaltyBan") or 0),
            displayDivisor=float(divisor) or 1.0,
            displayMultiplier=float(multiplier) or 1.0,
            noteOk=str(raw.get("noteOk") or "正常"),
            noteWarn=str(raw.get("noteWarn") or "警戒"),
            noteBan=str(raw.get("noteBan") or "达禁飞阈值"),
        )

    def banned(self, value: float) -> bool:
        if self.direction == "low":
            return self.banValue is not None and value <= float(self.banValue)
        if self.direction == "range":
            return ((self.banLow is not None and value < float(self.banLow))
                    or (self.banHigh is not None and value > float(self.banHigh)))
        return self.banValue is not None and value >= float(self.banValue)

    def warn(self, value: float) -> bool:
        if self.direction == "low":
            return self.warnValue is not None and value <= float(self.warnValue)
        if self.direction == "range":
            return ((self.warnLow is not None and value < float(self.warnLow))
                    or (self.warnHigh is not None and value > float(self.warnHigh)))
        return self.warnValue is not None and value >= float(self.warnValue)

    def display(self, raw: float) -> float:
        return raw / self.displayDivisor * self.displayMultiplier


@dataclass
class RuleSpec:
    version: str = "v1"
    hardBanEnabled: bool = True
    hardBanSfiCap: int = 39
    levels: Dict[str, int] = field(default_factory=lambda: {"fit": 80, "caution": 60, "danger": 40})
    factors: List[FactorRule] = field(default_factory=list)
    source: str = "built-in-defaults"

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], source: str = "config") -> "RuleSpec":
        levels = raw.get("levels") or {}
        factors_raw = raw.get("factors") or _DEFAULT_FACTORS
        return cls(
            version=str(raw.get("version") or "v1"),
            hardBanEnabled=bool(raw.get("hardBanEnabled", True)),
            hardBanSfiCap=int(raw.get("hardBanSfiCap") or 39),
            levels={
                "fit": int(levels.get("fit") or 80),
                "caution": int(levels.get("caution") or 60),
                "danger": int(levels.get("danger") or 40),
            },
            factors=[FactorRule.from_dict(f) for f in factors_raw] or [FactorRule.from_dict(f) for f in _DEFAULT_FACTORS],
            source=source,
        )


def load_spec(path: Optional[Path] = None) -> RuleSpec:
    """加载规则配置：指定路径 → 项目 config/rules-v1.json → 内置默认。"""
    candidate = Path(path) if path else RULES_PATH
    try:
        with open(candidate, "r", encoding="utf-8") as f:
            return RuleSpec.from_dict(json.load(f), source=str(candidate))
    except Exception:
        return RuleSpec.from_dict({}, source="built-in-defaults")


def _numeric(snapshot: Dict[str, Any], key: str) -> Optional[float]:
    value = snapshot.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evaluate(snapshot: Dict[str, Any], spec: Optional[RuleSpec] = None) -> Dict[str, Any]:
    """按配置计算规则结果。缺失/非法必需字段抛 ValueError（不得默认判定适飞）。"""
    rule_spec = spec or load_spec()
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    penalty = 0
    missing: List[str] = []

    for rule in rule_spec.factors:
        raw = _numeric(snapshot, rule.key)
        if raw is None:
            missing.append(rule.key)
            continue
        limits = RANGE_LIMITS.get(rule.key)
        if limits and not (limits[0] <= raw <= limits[1]):
            missing.append(rule.key)
            continue
        banned = rule.banned(raw)
        warn = (not banned) and rule.warn(raw)
        points = rule.penaltyBan if banned else (rule.penaltyWarn if warn else 0)
        note = rule.noteBan if banned else (rule.noteWarn if warn else rule.noteOk)
        penalty += points
        checks.append({
            "factor": rule.label,
            "value": round(rule.display(raw), 1),
            "unit": rule.unit,
            "banned": banned,
            "warn": warn,
            "penalty": points,
            "note": note,
        })
        if banned:
            reasons.append("%s %.1f %s %s" % (rule.label, rule.display(raw), rule.unit, rule.noteBan))
        elif warn:
            reasons.append("%s %.1f %s %s" % (rule.label, rule.display(raw), rule.unit, rule.noteWarn))

    if missing:
        raise ValueError("missing or invalid weather fields: " + ",".join(missing))

    raw_sfi = max(0, min(100, 100 - penalty))
    hard_ban = rule_spec.hardBanEnabled and any(c["banned"] for c in checks)
    sfi = min(raw_sfi, rule_spec.hardBanSfiCap) if hard_ban else raw_sfi
    level = level_of(sfi, rule_spec)

    return {
        "raw_sfi": raw_sfi,
        "sfi": sfi,
        "level": level,
        "level_label": LEVEL_LABELS_CN.get(level, level),
        "hard_ban": hard_ban,
        "penalty": penalty,
        "rule_version": rule_spec.version,
        "rule_source": rule_spec.source,
        "checks": checks,
        "reasons": reasons or ["各要素均在适飞阈值内"],
    }


def level_of(sfi: int, spec: Optional[RuleSpec] = None) -> str:
    rule_spec = spec or load_spec()
    levels = rule_spec.levels
    if sfi >= levels["fit"]:
        return "FIT"
    if sfi >= levels["caution"]:
        return "CAUTION"
    if sfi >= levels["danger"]:
        return "DANGER"
    return "BAN"
