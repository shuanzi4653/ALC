from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

FORMAT = 'alc-forest-v1'

class ModelError(ValueError):
    """模型文件与代码不匹配 —— 这不是"数据不好"，是部署错，必须显式失败。"""

class Forest:
    def __init__(self, payload: Dict[str, Any]):
        if payload.get('format') != FORMAT:
            raise ModelError('模型格式不是 %s：%r' % (FORMAT, payload.get('format')))
        self.payload = payload
        self.model_version = payload['modelVersion']
        self.labels_version = payload['labelsVersion']
        self.classes: List[str] = list(payload['classes'])
        self.feature_names: List[str] = list(payload['featureNames'])
        self.trees: List[Any] = payload['trees']
        self.defaults: Dict[str, float] = dict(payload.get('defaults') or {})
        self.importance: Dict[str, float] = dict(payload.get('featureImportance') or {})
        self.stats: Dict[str, Dict[str, float]] = dict(payload.get('trainStats') or {})
        self.provenance: Dict[str, Any] = dict(payload.get('provenance') or {})
        if not self.trees:
            raise ModelError('模型里一棵树都没有')

    def _leaf_counts(self, tree: Any, vector: List[float]) -> List[float]:
        node = tree
        while True:
            if isinstance(node, dict):
                if 'leaf' in node:
                    return [float(x) for x in node['leaf']]
                idx, thr = node['feature'], node['threshold']
                node = node['left'] if vector[idx] <= thr else node['right']
                continue
            if len(node) == len(self.classes) and all(isinstance(x, (int, float)) for x in node):
                return [float(x) for x in node]
            idx, thr, left, right = node[0], node[1], node[2], node[3]
            node = left if vector[idx] <= thr else right

    def predict(self, vector: List[float]) -> Dict[str, Any]:
        if len(vector) != len(self.feature_names):
            raise ModelError('特征数 %d 与模型要求的 %d 不一致（特征顺序错位会让预测静默变错）'
                             % (len(vector), len(self.feature_names)))
        totals = [0.0] * len(self.classes)
        for tree in self.trees:
            counts = self._leaf_counts(tree, vector)
            total = sum(counts)
            if total <= 0:
                continue
            for i, c in enumerate(counts):
                totals[i] += c / total
        grand = sum(totals) or 1.0
        probs = [t / grand for t in totals]
        best = max(range(len(probs)), key=lambda i: probs[i])
        return {
            'level': self.classes[best],
            'confidence': round(probs[best], 4),
            'probabilities': {name: round(p, 4) for name, p in zip(self.classes, probs)},
            'probabilitiesExact': {name: p for name, p in zip(self.classes, probs)},
        }

    def top_factors(self, vector: List[float], k: int = 3) -> List[Dict[str, Any]]:
        scored = []
        for i, name in enumerate(self.feature_names):
            if name.startswith('miss_'):
                continue
            imp = float(self.importance.get(name, 0.0))
            stat = self.stats.get(name) or {}
            mean = stat.get('mean')
            std = stat.get('std') or 0.0
            if imp <= 0 or not mean or std <= 0:
                continue
            z = abs(vector[i] - float(mean)) / float(std)
            scored.append({'feature': name, 'value': round(vector[i], 3),
                           'score': round(imp * z, 6)})
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:k]

def load(path) -> Forest:
    with open(Path(path), encoding='utf-8') as fh:
        return Forest(json.load(fh))
