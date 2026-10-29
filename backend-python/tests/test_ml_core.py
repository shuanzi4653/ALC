# -*- coding: utf-8 -*-
"""轨1 模型内核（0.10.1（Beta））的判据：判据 / 特征 / 打分器 / 服务。

这里的用例不是在验"模型准不准"（那个问题在 `tools/ml/label_report.py` 与
`data/training/model-v1-metrics.json`，且有分母），而是在验四件**错了也不会报错**的事：

1. 阵风有没有偷偷回到"绝对阈值"那条路上；
2. 运行时快照与训练样本的单位换算有没有被写反（0.62 当成 0.62% 喂进模型）；
3. 导出模型与代码的特征顺序/特征数不一致时，是**显式失败**还是"按位置凑合"；
4. 模型文件缺席时，服务返回的是"没有档位"，还是编了一个看起来正常的档位。
"""
import json

import pytest

from ml import features as F
from ml import labels as L
from ml import service as S
from ml.forest import Forest, ModelError


# ---------------------------------------------------------------- 判据 ----

def test_阵风不参与绝对阈值分段():
    """`windGust` 的 direction 是 `none` —— 它只进组合规则（阵风因子），不进分段。

    这条钉的是一个真实决策：`wind_gusts_10m` 的口径无法从接口自证（实测 p50 = 22.0 m/s、
    与平均风的比值 p50 = 2.49，而陆地常规阵风因子约 1.3–1.8）。照 18 m/s 判禁飞会把
    64% 的小时判成 BAN —— **量的不是天气，是字段口径**。所以阵风不给绝对阈值。
    若哪天有人"顺手补上"一个 18，这条会红。
    """
    spec = L.load_spec()
    assert spec.factors['windGust']['direction'] == 'none'
    assert spec.band_of('windGust', 30.0) is None
    assert spec.band_of('windGust', 99.0) is None


def test_取最坏档_而不是扣分累减():
    """判据是"逐要素分段 + 取最坏档"。累减扣分会让中档被两侧挤掉（实测 BAN 65%）。"""
    spec = L.load_spec()
    verdict = spec.label({'windSpeed': 8.6, 'windGust': 12.0, 'precipMmh': 10.0,
                          'visibilityM': 4000, 'tempC': 20, 'rhPct': 50})
    assert verdict['level'] == 'BAN'          # 降水 10 > danger 5
    assert verdict['bands']['precipMmh'] == 'BAN'
    assert verdict['bands']['windSpeed'] == 'CAUTION'   # 8.6 ∈ (8, 10]


def test_必需要素缺两个就弃权而不是猜():
    spec = L.load_spec()
    verdict = spec.label({'tempC': 20, 'rhPct': 50, 'windSpeed': 5})
    assert verdict['level'] == 'SKIP'
    assert '宁可不标' in verdict['reason']
    # 缺一个仍可标，但要把缺席记进 missing —— 让调用方能讲出"这一档是基于 3/4 个要素"。
    partial = spec.label({'windSpeed': 5, 'windGust': 9, 'precipMmh': 0, 'tempC': 20, 'rhPct': 50})
    assert partial['level'] in L.LEVELS
    assert 'visibilityM' in partial['missing']


def test_阵风因子可以升档_但平均风太小时不适用():
    spec = L.load_spec()
    # 8.0 / 2.5 = 3.2 → 恰好不 > 3.2，停在 CAUTION
    caution = spec.label({'windSpeed': 2.5, 'windGust': 8.0, 'precipMmh': 0,
                          'visibilityM': 20000, 'tempC': 20, 'rhPct': 50})
    assert caution['level'] == 'FIT'      # 平均风 < 3 m/s ⇒ 比值不参与
    strong = spec.label({'windSpeed': 5.0, 'windGust': 17.0, 'precipMmh': 0,
                         'visibilityM': 20000, 'tempC': 20, 'rhPct': 50})
    assert strong['level'] == 'DANGER'    # 3.4 > 3.2
    assert strong['bands']['_combination'] == 'DANGER'


def test_低温高湿记为结冰谨慎():
    spec = L.load_spec()
    verdict = spec.label({'windSpeed': 3.0, 'windGust': 5.0, 'precipMmh': 0,
                          'visibilityM': 20000, 'tempC': 0.5, 'rhPct': 95})
    assert verdict['level'] == 'CAUTION'
    assert '结冰' in verdict['reason']


def test_判据与运行规则是两份文件_不是同一个():
    """两份文件回答两个问题，关系是 `DISTINCT_BY_DESIGN`，不是"还没合并"。"""
    spec = L.load_spec()
    assert spec.raw['relationToRuntimeRules']['relationship'] == 'DISTINCT_BY_DESIGN'
    assert spec.raw['aggregation']['method'] == 'worst-band'
    # 出处要如实：查不到公开出处的写 ENGINEERING，不硬凑一个引用。
    assert spec.raw['provenance']['kind'] in ('ENGINEERING', 'PUBLIC')


# ---------------------------------------------------------------- 特征 ----

def test_湿度云量按0到1换算_已经是百分数时原样返回():
    # 只按"乘 100"处理，历史样本会被放大成 6200%，模型立刻崩 —— **但不会报错**。
    assert F._scale_percent(0.62) == pytest.approx(62.0)
    assert F._scale_percent(62.0) == pytest.approx(62.0)
    assert F._scale_percent(None) is None
    assert F._scale_percent(True) is None      # bool 是 int 子类，必须先挡掉


def test_运行时与样本的同名要素量纲一致():
    """这条是同型 bug 的唯一网：训练叫 rhPct(0–100)、线上叫 humidity(0–1)。

    写反了不会报错，只会让模型拿 0.62% 的相对湿度做判断，然后给出一个看起来正常的档位。
    """
    runtime = F.from_runtime({'humidity': 0.62, 'cloudCover': 0.35, 'windSpeed': 6.0})
    sample = F.from_sample({'rhPct': 62.0, 'cloudPct': 35.0, 'windMps': 6.0})
    assert runtime['rhPct'] == pytest.approx(sample['rhPct'])
    assert runtime['cloudPct'] == pytest.approx(sample['cloudPct'])
    assert runtime['windSpeed'] == pytest.approx(sample['windSpeed'])


def test_缺测点亮miss标志且不填0():
    vec = F.vector(F.from_runtime({'windSpeed': 6.0}), {name: -1.0 for name in F.FEATURE_NAMES})
    index = {name: i for i, name in enumerate(F.FEATURE_NAMES)}
    assert vec[index['miss_wind']] == 0.0
    assert vec[index['miss_vis']] == 1.0
    assert vec[index['miss_precip']] == 1.0
    # 缺席用训练中位数（此处显式给 -1）填，而不是 0 —— 0 在这里是一个**有意义的读数**。
    assert vec[index['visibilityM']] == -1.0


def test_特征数固定_改顺序必须重训():
    """顺序即模型输入顺序。导出的模型 JSON 会带上这份顺序，加载时逐项核对。"""
    assert len(F.FEATURE_NAMES) == 16
    assert F.FEATURE_NAMES[0] == 'windSpeed'
    assert len(F.vector(F.from_runtime({}), {name: 0.0 for name in F.FEATURE_NAMES})) == 16


# -------------------------------------------------------------- 打分器 ----

def toy_forest():
    return {
        'format': 'alc-forest-v1',
        'modelVersion': 'toy',
        'labelsVersion': 'v1',
        'classes': ['FIT', 'CAUTION', 'DANGER', 'BAN'],
        'featureNames': ['windSpeed'],
        'defaults': {'windSpeed': 0.0},
        'featureImportance': {'windSpeed': 1.0},
        'trainStats': {'windSpeed': {'mean': 8.0, 'std': 4.0}},
        # 单棵树：windSpeed <= 10 → FIT，否则 DANGER
        'trees': [[0, 10.0, [1, 0, 0, 0], [0, 0, 1, 0]]],
    }


def test_单棵树打分():
    forest = Forest(toy_forest())
    assert forest.predict([5.0])['level'] == 'FIT'
    assert forest.predict([15.0])['level'] == 'DANGER'
    assert forest.predict([10.0])['level'] == 'FIT'    # <= 走左支
    prob = forest.predict([15.0])['probabilities']
    assert prob['DANGER'] == pytest.approx(1.0)


def test_特征数不符必须显式失败_不许按位置凑合():
    forest = Forest(toy_forest())
    with pytest.raises(ModelError):
        forest.predict([1.0, 2.0])
    with pytest.raises(ModelError):
        forest.predict([])


def test_格式不符必须显式失败():
    doc = toy_forest()
    doc['format'] = 'pickle-v0'
    with pytest.raises(ModelError):
        Forest(doc)
    empty = toy_forest()
    empty['trees'] = []
    with pytest.raises(ModelError):
        Forest(empty)


def test_top3是近似归因_不是SHAP():
    forest = Forest(toy_forest())
    factors = forest.top_factors([20.0], k=3)
    assert factors and factors[0]['feature'] == 'windSpeed'
    # miss_* 标志不参与归因（它们是"有没有量到"，不是气象量）。
    assert all(not item['feature'].startswith('miss_') for item in factors)


# ---------------------------------------------------------------- 服务 ----

def test_模型文件缺席时不给任何档位(monkeypatch):
    # 指向一个**不存在**的相对路径。不用 tmp_path：沙箱下临时目录会报 PermissionError，
    # 而那会把"模型缺席"这条用例演成"量具坏了"（`notes/sandbox-traps.md`）。
    monkeypatch.setenv('ALC_ML_MODEL', 'no-such-model-file.json')
    S.load(force=True)
    result = S.predict({'windSpeed': 5.0})
    assert result['available'] is False
    assert result['status'] == 'MODEL_NOT_FOUND'
    # 关键：没有 level 键。编一个档位比不返回更糟。
    assert 'level' not in result
    monkeypatch.delenv('ALC_ML_MODEL', raising=False)
    S.load(force=True)


def test_模型可用时返回溯源与降级标记(monkeypatch):
    model_path = S.DEFAULT_MODEL
    if not model_path.is_file():
        pytest.skip('模型文件不在（未训练过）')
    monkeypatch.delenv('ALC_ML_MODEL', raising=False)
    S.load(force=True)
    ok = S.predict({'windSpeed': 4.0, 'windGust': 7.0, 'precipMmh': 0.0,
                    'visibilityM': 22000, 'tempC': 18.0, 'humidity': 0.5,
                    'cloudCover': 0.3, 'pressureHpa': 1008.0})
    assert ok['available'] is True
    assert ok['status'] == 'OK'
    assert ok['level'] in L.LEVELS
    assert ok['provenance']['labelsSha256']
    assert ok['decidedBy'] == 'MODEL'
    assert '不是逐条 SHAP' in ok['attribution']

    # 缺测过半：必须标 degraded（中位数填充），而不是给一个看起来正常的高置信档位。
    thin = S.predict({'windSpeed': 6.0, 'tempC': 12.0, 'humidity': 0.6})
    assert thin['degraded']['flag'] is True
    assert '中位数填充' in thin['degraded']['reason']
    assert len(thin['missingFeatures']) >= 3


def test_status报告的是模型自己的版本而不是代码里的常量(monkeypatch):
    monkeypatch.delenv('ALC_ML_MODEL', raising=False)
    S.load(force=True)
    status = S.status()
    if not status['available']:
        pytest.skip('模型文件不在（未训练过）')
    assert status['modelVersion'] == 'ml-v1'
    assert status['featureCount'] == len(F.FEATURE_NAMES)
    assert status['trees'] >= 1
    # 训练溯源要能被读出来 —— 报告里"这批结论是哪一版模型给的"只有这一个来源。
    assert status['provenance']['labelSource'].startswith('rule-label-spec')
    assert status['provenance']['sklearn']


def test_导出的模型文件格式与代码版本一致(monkeypatch):
    model_path = S.DEFAULT_MODEL
    if not model_path.is_file():
        pytest.skip('模型文件不在（未训练过）')
    payload = json.loads(model_path.read_text(encoding='utf-8'))
    assert payload['format'] == 'alc-forest-v1'
    assert payload['featureNames'] == list(F.FEATURE_NAMES)
    assert payload['labelsVersion'] == L.load_spec().version
    # `classes` 是 **sklearn 的字母序**（BAN/CAUTION/DANGER/FIT），不是 LEVELS 的严重度序。
    # 这不是缺陷：叶子里的计数按同一个顺序排列，`predict` 用同一份 `classes` 取名，
    # 所以两边一致（parity 已逐条验过）。但它必须与叶子顺序**同源** —— 一旦有人
    # 为了"看起来顺眼"把这里改成 LEVELS 序，而不重排叶子，每个档位都会错位。
    # 因此只断言集合相等，并断言顺序就是 sklearn 的字母序。
    assert sorted(payload['classes']) == sorted(L.LEVELS)
    assert payload['classes'] == sorted(L.LEVELS), '叶子计数按 sklearn 字母序排列，改名次即错位'
    # 标签来源必须是判据，不是 DeepSeek —— 后者只作独立第二标注员。
    assert payload['provenance']['labelSource'].startswith('rule-label-spec')
    assert payload['provenance']['independentAnnotation']['weightedKappa'] > 0
