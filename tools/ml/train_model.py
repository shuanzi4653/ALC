# -*- coding: utf-8 -*-
"""0.10.1 训练与导出（**离线**：需要 sklearn；运行时不需要）。

用哪个解释器：本仓的 `backend-python/.venv` **故意不装 sklearn**（运行时不该为推理拉
scipy）。训练用本机 Anaconda 的解释器（实测 sklearn 1.4.2 / numpy 1.26.4），
版本号写进模型 JSON 的 provenance —— 换机器换版本时，"指标是哪一版算出来的"有据可查。

三件必须做的事，缺一件这份模型就不该上评测表：
1. **按时间切分**（不是随机切）。打乱切分会让"未来小时"进训练集，指标虚高。
2. **危险档漏报单独报**。四档不平衡时报 accuracy 等于自欺。
3. **导出后逐条 parity**：sklearn 的 `predict` 与纯 Python 打分器在同一测试集上必须
   100% 一致。不一致说明导出走样，指标全部作废。
"""
import argparse
import hashlib
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

import numpy as np  # noqa: E402
from sklearn.ensemble import (ExtraTreesClassifier, HistGradientBoostingClassifier,  # noqa: E402
                              RandomForestClassifier)
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import classification_report, confusion_matrix, f1_score  # noqa: E402

from ml import features as F  # noqa: E402
from ml import labels as L  # noqa: E402
from ml.forest import Forest  # noqa: E402

DATA = ROOT / 'data' / 'training'
MODELS = ROOT / 'models'
CLASSES = ['FIT', 'CAUTION', 'DANGER', 'BAN']
DANGER_SET = {'DANGER', 'BAN'}


def load_rows():
    """训练标签取**判据**（`config/labels-v1.json`），不取 DeepSeek 输出。

    这不是"顺手"，是一个有代价的选择，理由写在这里免得以后有人再问一遍：
    - DeepSeek 那一版不给 FIT（1133 条里只有 27 条），四档里最轻的一档几乎缺席，
      拿它训练等于教模型"这个世界只有三种天气"，而 FIT 恰恰是最常出现的档。
    - 差距不是随机噪声而是**系统性的一档偏移**：rationale 里把「7.5 m/s，接近 8 m/s
      阈值」判成 CAUTION —— 判据里 7.5 < 8 就是 FIT。随机噪声能靠多标抵消，系统偏移不能。
    - 但 1133 条没白跑：它是**独立的第二标注员**，量的是"同一份判据换一个人按同样读法
      能否复现"，结果 κ=0.7946 已存 `data/training/label-agreement.json`。这条数比
      "模型准确率"更能说明判据本身没写歪。
    """
    spec = L.load_spec()
    rows = []
    skipped = 0
    for line in io.open(DATA / 'samples-v1.jsonl', encoding='utf-8'):
        if not line.strip():
            continue
        raw = json.loads(line)
        canon = F.from_sample(raw)
        verdict = spec.label(canon)
        if verdict['level'] not in CLASSES:
            skipped += 1
            continue
        raw = dict(raw)
        raw['monthNum'] = int(raw['month'][5:7])
        raw['label'] = verdict['level']
        raw['labelReason'] = verdict['reason']
        rows.append(raw)
    rows.sort(key=lambda r: r['timeLocal'])
    print('[INFO] 标签源 = 判据 %s（%s）；SKIP %d 条'
          % (spec.version, L.DEFAULT_PATH.name, skipped))
    return rows


def agreement_note():
    """把"判据 vs DeepSeek"的实测一致性带进模型 provenance —— 判据可不可信要有旁证。"""
    path = DATA / 'label-agreement.json'
    if not path.exists():
        return None
    try:
        data = json.load(io.open(path, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None
    agg = data.get('agreement') or {}
    return {'raw': agg.get('raw'), 'weightedKappa': agg.get('weightedKappa'),
            'n': agg.get('n'), 'source': 'data/training/label-agreement.json'}


def build_xy(rows):
    canon = [F.from_sample(r) for r in rows]
    # 缺失值填充用**训练段的中位数**（后面再改成 train 部分），这里先给全 0 占位
    placeholder = {name: 0.0 for name in F.FEATURE_NAMES}
    X = [F.vector(c, placeholder) for c in canon]
    y = [r['label'] for r in rows]
    return X, y


def tree_to_compact(estimator, classes):
    def node(clf, i):
        left = clf.tree_.children_left[i]
        right = clf.tree_.children_right[i]
        if left == -1 and right == -1:
            counts = clf.tree_.value[i][0]
            total = float(counts.sum()) or 1.0
            return [round(float(c) / total, 6) for c in counts]
        return [int(clf.tree_.feature[i]), round(float(clf.tree_.threshold[i]), 6),
                node(clf, int(left)), node(clf, int(right))]
    return [node(t, 0) for t in estimator.estimators_]


def metrics(y_true, y_pred):
    labels = [c for c in CLASSES if c in set(y_true) | set(y_pred)]
    cm = confusion_matrix(y_true, y_pred, labels=labels).tolist()
    rep = classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)
    per = {k: {m: round(v, 4) for m, v in rep[k].items() if m in
               ('precision', 'recall', 'f1-score', 'support')} for k in labels}
    danger_true = [1 if t in DANGER_SET else 0 for t in y_true]
    danger_pred = [1 if p in DANGER_SET else 0 for p in y_pred]
    tp = sum(1 for t, p in zip(danger_true, danger_pred) if t == 1 and p == 1)
    fn = sum(1 for t, p in zip(danger_true, danger_pred) if t == 1 and p == 0)
    fp = sum(1 for t, p in zip(danger_true, danger_pred) if t == 0 and p == 1)
    return {
        'labels': labels,
        'confusion': cm,
        'perClass': per,
        'macroF1': round(f1_score(y_true, y_pred, labels=labels, average='macro'), 4),
        'accuracy': round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / max(1, len(y_true)), 4),
        'dangerMiss': fn,
        'dangerHit': tp,
        'dangerFalseAlarm': fp,
        'dangerRecall': round(tp / (tp + fn), 4) if (tp + fn) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trees', type=int, default=300)
    args = ap.parse_args()

    rows = load_rows()
    if len(rows) < 200:
        print('[FAIL] 可用标注样本只有 %d 条 —— 量具没量成，不能当通过' % len(rows))
        return 2
    print('[INFO] 有标注样本 %d 条；档位分布 %s'
          % (len(rows), dict(Counter(r['label'] for r in rows))))

    X, y = build_xy(rows)
    n = len(rows)
    i_tr, i_va = int(n * 0.70), int(n * 0.85)
    Xtr, ytr = X[:i_tr], y[:i_tr]
    Xva, yva = X[i_tr:i_va], y[i_tr:i_va]
    Xte, yte = X[i_va:], y[i_va:]
    print('[INFO] 时间切分 训练 %d / 验证 %d / 测试 %d（按 timeLocal 升序，不打乱）'
          % (len(Xtr), len(Xva), len(Xte)))
    print('[INFO] 训练段档位 %s；测试段档位 %s'
          % (dict(Counter(ytr)), dict(Counter(yte))))

    # 缺失填充用**训练段中位数**，再重建全部向量
    train_defaults = {}
    for j, name in enumerate(F.FEATURE_NAMES):
        vals = [row[j] for i, row in enumerate(X) if i < i_tr]
        train_defaults[name] = float(np.median(vals))
    canon = [F.from_sample(r) for r in rows]
    X = [F.vector(c, train_defaults) for c in canon]
    Xtr, Xva, Xte = X[:i_tr], X[i_tr:i_va], X[i_va:]

    results = {}
    models = {}

    et = ExtraTreesClassifier(n_estimators=args.trees, class_weight='balanced',
                              random_state=42, n_jobs=-1)
    et.fit(Xtr, ytr)
    models['ExtraTrees'] = et

    # 对照模型：**默认参数 + 同样的类别权重**，不做超参搜索。
    # 理由：横向对比表要证明"换模型有差别"，不要变成"谁调参调得久"。
    rf = RandomForestClassifier(n_estimators=200, class_weight='balanced', random_state=42, n_jobs=-1)
    rf.fit(Xtr, ytr)
    models['RandomForest'] = rf

    lr = LogisticRegression(max_iter=2000, class_weight='balanced', random_state=42)
    lr.fit(Xtr, ytr)
    models['LogisticRegression'] = lr

    try:
        hgb = HistGradientBoostingClassifier(random_state=42)
        hgb.fit(Xtr, ytr)
        models['HistGradientBoosting'] = hgb
    except Exception as exc:  # noqa: BLE001
        print('[WARN] HistGradientBoosting 训练失败：%s' % exc)

    for name, model in models.items():
        pred = list(model.predict(Xte))
        results[name] = metrics(yte, pred)
        print('[指标] %-22s macroF1=%.4f acc=%.4f 危险漏报=%d/%d'
              % (name, results[name]['macroF1'], results[name]['accuracy'],
                 results[name]['dangerMiss'],
                 results[name]['dangerMiss'] + results[name]['dangerHit']))

    # 规则基线（同一测试集，用运行规则判）
    sys.path.insert(0, str(ROOT / 'backend-python'))
    import rules as rule_mod  # noqa: E402
    rule_pred, rule_idx = [], []
    for offset, r in enumerate(rows[i_va:]):
        snap = {'windSpeed': r['windMps'], 'windGust': r['gustMps'],
                'precipMmh': r['precipMmh'], 'visibilityM': r['visibilityM'],
                'tempC': r['temperatureC']}
        try:
            level = rule_mod.evaluate(snap)['level']
        except ValueError:
            # 规则拒判的样本**不计入**对照。以前这里会 fallback 成 FIT ——
            # 那等于让基线"白捡"正确率，对照表随即变成假证据。
            continue
        rule_pred.append(level)
        rule_idx.append(offset)
    yte_rule = [yte[k] for k in rule_idx]
    if rule_pred:
        results['RuleBaseline'] = metrics(yte_rule, rule_pred)
        results['RuleBaseline']['evaluated'] = len(rule_pred)
        results['RuleBaseline']['abstained'] = len(yte) - len(rule_pred)
        print('[指标] %-22s macroF1=%.4f acc=%.4f 危险漏报=%d/%d（弃权 %d 条不计入）'
              % ('RuleBaseline', results['RuleBaseline']['macroF1'], results['RuleBaseline']['accuracy'],
                 results['RuleBaseline']['dangerMiss'],
                 results['RuleBaseline']['dangerMiss'] + results['RuleBaseline']['dangerHit'],
                 len(yte) - len(rule_pred)))
    else:
        # 对照侧全弃权 = 这一行没有可比性，写 unavailable 而不是写一个 0。
        results['RuleBaseline'] = {'macroF1': None, 'unavailable': 'ALL_ABSTAINED'}
        print('[WARN] 规则基线全部拒判 —— 对照不可用')

    # 选主模型：只看 macroF1（危险漏报另列，不作硬选择依据，避免把小概率档过拟合）
    ranked = [k for k in ('ExtraTrees', 'RandomForest', 'LogisticRegression',
                          'HistGradientBoosting') if k in results]
    best_name = max(ranked, key=lambda k: results[k]['macroF1'] if results[k]['macroF1'] is not None else -1)
    print('[选择] 指标最高 = %s' % best_name)

    # 能导出成纯 Python 树的只有两类。若最高分落在 LR/HGB 上，仍导出同类最优树模型，
    # 并把"为什么不是你"写进模型文件 —— 否则将来一定会有人问"指标对不上"。
    EXPORTABLE = ('ExtraTrees', 'RandomForest')
    chosen = best_name
    if chosen not in EXPORTABLE:
        chosen = max(EXPORTABLE, key=lambda k: results[k]['macroF1'])
        print('[选择] %s 无法导出为树，改导出 %s（macroF1 %+.4f）'
              % (best_name, chosen, results[chosen]['macroF1'] - results[best_name]['macroF1']))
    best = models[chosen]
    classes = [str(c) for c in best.classes_]

    # ---- 导出 ----
    payload = {
        'format': 'alc-forest-v1',
        'modelVersion': 'ml-v1',
        'labelsVersion': 'v1',
        'labelsSha256': hashlib.sha256((ROOT / 'config' / 'labels-v1.json').read_bytes()).hexdigest(),
        'datasetSha256': json.load(io.open(DATA / 'dataset-v1.json', encoding='utf-8'))['sha256'],
        'classes': classes,
        'featureNames': list(F.FEATURE_NAMES),
        'defaults': train_defaults,
        'featureImportance': {name: round(float(v), 8) for name, v in
                              zip(F.FEATURE_NAMES, getattr(best, 'feature_importances_', np.zeros(len(F.FEATURE_NAMES))))},
        'trainStats': {name: {'mean': round(float(np.mean([row[j] for row in Xtr])), 6),
                              'std': round(float(np.std([row[j] for row in Xtr])), 6)}
                       for j, name in enumerate(F.FEATURE_NAMES)},
        'trees': tree_to_compact(best, classes),
        'selection': {'chosen': chosen, 'bestByMetric': best_name,
                      'by': 'macroF1 on time-split test set',
                      'exportableOnly': list(EXPORTABLE),
                      'note': ('导出侧只能是树（纯 Python 打分器）。若 bestByMetric 与 chosen 不同，'
                               '原因是前者无法导出，指标差异见 candidates。'),
                      'candidates': {k: v.get('macroF1') for k, v in results.items()}},
        'provenance': {
            'trainedAt': '2026-10-17',
            'sklearn': __import__('sklearn').__version__,
            'numpy': np.__version__,
            'python': sys.version.split()[0],
            'samples': len(rows),
            'trainSizes': [len(Xtr), len(Xva), len(Xte)],
            'split': 'time-ordered 70/15/15 by timeLocal, no shuffle',
            'classWeight': 'balanced',
            'hyperparamSearch': 'none (default params for all candidates)',
            'labelSource': 'rule-label-spec (config/labels-v1.json)',
            'labelSourceReason': ('DeepSeek v1 标注不给 FIT（1133 条仅 27 条）且为系统性一档偏移，'
                                  '不作训练标签；仅作独立第二标注员，见 independentAnnotation'),
            'independentAnnotation': agreement_note(),
            'dsLabelsSha256': (hashlib.sha256((DATA / 'labels-v1.jsonl').read_bytes()).hexdigest()
                               if (DATA / 'labels-v1.jsonl').exists() else None),
            'pressureNote': F.pressureNote,
        },
        'metrics': results,
        'metricsNote': (
            '标签来自 rule-label-spec（config/labels-v1.json）。因此本表的准确率衡量的是'
            '「模型对判据的复现能力」，不是「模型对天气的预测能力」—— 后者需要独立观测真值，'
            '本仓没有。RuleBaseline 行用的是运行规则 rules-v1.json（另一套阈值与另一套聚合方式），'
            '它与本模型回答的不是同一个问题，两者不可直接比优劣，只能各自独立解读。'
        ),
    }
    MODELS.mkdir(parents=True, exist_ok=True)
    with io.open(MODELS / 'ml-v1.json', 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(payload, fh, ensure_ascii=False)
    size = (MODELS / 'ml-v1.json').stat().st_size
    print('[OK] 导出 %s（%.1f KB，%d 棵树）' % (MODELS / 'ml-v1.json', size / 1024, len(payload['trees'])))

    # ---- parity：导出后逐条比对 ----
    # 用**批量** predict 一次算完再逐条比：逐条调 predict 会在 sklearn 侧反复做输入校验，
    # 慢到让人想跳过这一步 —— 而这一步是"指标是否还成立"的唯一开关。
    forest = Forest(json.loads((MODELS / 'ml-v1.json').read_text(encoding='utf-8')))
    want_all = [str(x) for x in best.predict(Xte)]
    mism = []
    for i, vec in enumerate(Xte):
        got = forest.predict(vec)['level']
        if got != want_all[i]:
            mism.append((rows[i_va + i]['sampleId'], want_all[i], got))
    print('[parity] 测试集 %d 条，不一致 %d 条' % (len(Xte), len(mism)))
    if mism:
        print('[FAIL] 导出走样，前 5 条：%s' % mism[:5])
        return 1

    with io.open(DATA / 'model-v1-metrics.json', 'w', encoding='utf-8', newline='\n') as fh:
        json.dump({'metrics': results, 'chosen': chosen, 'bestByMetric': best_name,
                   'parity': '100%', 'parityTested': len(Xte),
                   'testSize': len(Xte), 'samples': len(rows),
                   'metricsNote': payload['metricsNote'],
                   'labelSource': payload['provenance']['labelSource'],
                   'independentAnnotation': payload['provenance']['independentAnnotation']},
                  fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
