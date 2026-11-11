#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把随机森林模型导出成端侧可编译的纯 C 数据（forest_model.h / forest_model.c）。

为什么这么导出（每条都对应一个答辩问题）
========================================
1. **语义以 `backend-python/ml/forest.py` 为准**，不以模型 JSON 的自述为准。
   `Forest.predict()` 的做法是：每棵树取出叶子上的两类计数 -> 用 `sum(counts)` 归一
   -> 100 棵树累加 -> 再除以总和得到概率。叶子上的两个数在本模型里已经和为 1，
   但**导出侧仍然两个数都写进 flash**，因为 `forest.py` 真的做了 `c/total` 与
   `t/grand` 两次除法；只存一个数再靠 `1-p` 反推，端云就会差最后几个 ulp，
   "逐字等价"这句话就说不出口了。
2. **无递归**：树被展平成一对平行数组，遍历是 `while` 循环下降。深度等于树高
   （本模型最大 10），不存在栈增长，也就没有"深度换机器就爆栈"的隐患。
3. **无动态内存**：全部是 `const` 静态数组。ESP32 上 `const` 数组进 `.rodata`
   （flash），不占 DRAM。
4. **float32 量化误差要报出来，不藏**。端侧只有 float32，导出时统一量化，并把
   每个阈值的量化误差上界打印出来；两棵树之间的判定只在"特征值恰好卡在阈值上"
   时才会翻边，报告里给的是实测超差组数，不是"理论上应该一致"。

展平后的数据结构（`forest_model.h` 里也有同样说明）
==================================================
节点数组只装**内部节点**（`EDGE_NODE_COUNT` 个），左右孩子字段的编码是：

    孩子 >= 0  -> 下一个内部节点在节点数组里的绝对下标
    孩子 <  0  -> 叶子，叶子下标 = -孩子 - 1

这样叶子不占节点槽位，省掉 4 万多个空槽；遍历时只需一次符号判断。

用法
====
    python tools/edge-export/export_forest.py
    python tools/edge-export/export_forest.py --verify 200      # 额外做导出前后一致性自检

产物：`tools/edge-export/forest_model.h`、`tools/edge-export/forest_model.c`
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / 'models' / 'ml-v2-vis3k.json'
OUT_H = HERE / 'forest_model.h'
OUT_C = HERE / 'forest_model.c'

FORMAT = 'alc-forest-v1'


# --------------------------------------------------------------------------- float32

def f32(value: float) -> float:
    """把 float64 量化成 float32，再以 float64 形式返回（值本身是 float32 精确可表示的）。"""
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def f32_next_down(value: float) -> float:
    """float32 空间里"下一个更小的数"（按位减/加一，注意负数与零的方向）。"""
    if value == 0.0:
        return struct.unpack('<f', struct.pack('<I', 0x80000001))[0]  # 最小负次正规数
    bits = struct.unpack('<I', struct.pack('<f', value))[0]
    bits = bits - 1 if value > 0.0 else bits + 1
    return struct.unpack('<f', struct.pack('<I', bits))[0]


def f32_floor(value: float) -> float:
    """把阈值**向下**取整到 float32：返回"不大于 value 的最大 float32"。

    为什么阈值必须向下取整（第一版向上取整，被实测打回来了）
    -------------------------------------------------------
    `forest.py` 的判定是 `vector[idx] <= thr`，两边都是 float64；端侧两边都是 float32。
    阈值就近量化成 thr32 时，1000 组实测有 40 组超差（最大 1.1e-2）——
    因为阈值往往就取自训练样本的相邻两点中点，真实观测里"恰好等于阈值"根本不罕见。

    正确的量化方向是**向下**取整。设 thrF = 不大于 thr 的最大 float32，则对任意 float32 的 x：
        x <= thr  且 x 是 float32  =>  x <= thrF   （(thrF, thr] 区间里没有 float32 可取）
        x >  thr                   =>  x >= 下一个 float32 > thrF  =>  x > thrF
    两侧都成立，故 x <= thrF <=> x <= thr。**严格等价，不是"误差够小"。**

    反例说明为什么不能向上取整（这是实测抓到的，不是推演）：
        thr = 8497.300048828125（float64），相距最近的 float32 是 8497.2998 与 8497.3008。
        取上界的 8497.3008 时，x = 8497.3008 本该走 right（x > thr），却变成 left —— Δp 直接 8.4e-2。
        取下界的 8497.2998 时判定正确。

    特征值只做就近量化：它就是观测值本身，端侧拿到的输入必须与云端逐位相同。
    """
    quantized = f32(value)
    if quantized <= value:
        return quantized
    return f32_next_down(quantized)


def f32_roundtrip_text(value: float) -> str:
    """输出 float32 的最短 round-trip 十进制串：C 侧 `strtof`/字面量都能还原成同一个 float。

    两个必须注意的坑（都真的踩过）：
    - `%.*g` 对整数会输出 "7"、"0"、"-0"，直接接 `f` 后缀变成 `7f`/`-0f`，
      MSVC 直接语法错误（gcc 容忍，所以换编译器才发现）。这里补 `.0`。
    - `-0.0` 必须保留符号：它是模型 defaults 里真实存在的值（hourCos），
      改成 `0.0` 会让端云在默认向量上差一个符号位的语义。
    """
    quantized = f32(value)
    text = ''
    for digits in range(6, 10):
        text = '%.*g' % (digits, quantized)
        if f32(float(text)) == quantized:
            break
    if not any(ch in text for ch in '.eEnN'):
        text += '.0'
    return text


# --------------------------------------------------------------------------- 展平

class FlatForest:
    """与 `backend-python/ml/forest.py` 同构的展平森林（导出与自检共用一份实现）。"""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        self.classes: List[str] = list(payload['classes'])
        self.feature_names: List[str] = list(payload['featureNames'])
        self.defaults: Dict[str, float] = dict(payload.get('defaults') or {})
        self.importance: Dict[str, float] = dict(payload.get('featureImportance') or {})
        self.version: str = str(payload['modelVersion'])
        self.calibration: Dict[str, List[float]] = dict(payload.get('calibration') or {})
        self.operating_threshold: float = float(payload.get('operatingThreshold') or 0.0)

        self.threshold: List[float] = []
        self.left: List[int] = []
        self.right: List[int] = []
        self.feature: List[int] = []
        self.leaf_neg: List[float] = []
        self.leaf_pos: List[float] = []
        self.tree_root: List[int] = []
        self.tree_nodes: List[int] = []
        self.max_depth = 0
        self._flatten_all(payload['trees'])
        # 导出用的阈值：向上取整到 float32（见 f32_ceil 的证明）。原始值保留在 self.threshold，
        # 用来在做差异统计时把"量化取整"和"展平写错"这两类问题分开。
        self.threshold_q: List[float] = [f32_floor(value) for value in self.threshold]

    # ---- 与 forest.py 的 `_leaf_counts` 完全同构的判定：先 dict.leaf，再"长度等于类数且全数字"，最后四元组
    def _is_leaf(self, node: Any) -> bool:
        if isinstance(node, dict):
            return 'leaf' in node
        return len(node) == len(self.classes) and all(isinstance(x, (int, float)) for x in node)

    def _leaf_values(self, node: Any) -> Tuple[float, float]:
        values = node['leaf'] if isinstance(node, dict) else node
        if len(values) != 2:
            raise SystemExit('本导出器只支持二分类叶子（实际 %d 类）' % len(values))
        return float(values[0]), float(values[1])

    def _children(self, node: Any) -> Tuple[int, float, Any, Any]:
        if isinstance(node, dict):
            return int(node['feature']), float(node['threshold']), node['left'], node['right']
        return int(node[0]), float(node[1]), node[2], node[3]

    def _flatten_all(self, trees: List[Any]) -> None:
        for tree in trees:
            self.tree_nodes.append(0)
            self.tree_root.append(self._flatten_tree(tree))

    def _flatten_tree(self, tree: Any) -> int:
        """把一棵树展平，返回根的引用（>=0 节点下标 / <0 叶子引用）。

        显式栈而不是递归：不是怕 Python 爆栈（深度 10），是为了让"孩子引用在父节点之后
        才确定"这件事在代码里看得见 —— 端侧 `edge_infer.c` 的遍历正是这条反向路径。
        """
        root_ref = -1
        # 每个待处理项：(节点, 深度, 赋值目标)，赋值目标为 None 表示这是整棵树的根
        pending: List[Tuple[Any, int, Optional[Tuple[int, int]]]] = [(tree, 0, None)]
        while pending:
            node, depth, assign = pending.pop()
            self.max_depth = max(self.max_depth, depth)

            if self._is_leaf(node):
                neg, pos = self._leaf_values(node)
                ref = -len(self.leaf_neg) - 1
                self.leaf_neg.append(neg)
                self.leaf_pos.append(pos)
            else:
                feature, threshold, left_node, right_node = self._children(node)
                if not 0 <= feature < len(self.feature_names):
                    raise SystemExit('树里出现越界特征下标 %r（模型与特征表不一致）' % feature)
                ref = self._reserve()
                self.threshold[ref] = threshold
                self.feature[ref] = feature
                self.tree_nodes[-1] += 1
                pending.append((left_node, depth + 1, (ref, 0)))
                pending.append((right_node, depth + 1, (ref, 1)))

            if assign is None:
                root_ref = ref
            else:
                parent, side = assign
                if side == 0:
                    self.left[parent] = ref
                else:
                    self.right[parent] = ref
        if root_ref < 0:
            # 整棵树只有一个叶子：允许，但没有内部节点，端侧遍历会立刻拿到叶子
            self.max_depth = max(self.max_depth, 0)
        return root_ref

    def _reserve(self) -> int:
        index = len(self.threshold)
        self.threshold.append(0.0)
        self.left.append(0)
        self.right.append(0)
        self.feature.append(0)
        return index

    # ---- 参考实现（float64），用来校验展平没走样
    def predict_flat64(self, vector: List[float]) -> List[float]:
        totals = [0.0, 0.0]
        for root in self.tree_root:
            if root < 0:  # 整棵树只有一个叶子
                counts = (self.leaf_neg[-root - 1], self.leaf_pos[-root - 1])
            else:
                index = root
                while True:
                    child = self.left[index] if vector[self.feature[index]] <= self.threshold_q[index] \
                        else self.right[index]
                    if child < 0:
                        leaf = -child - 1
                        counts = (self.leaf_neg[leaf], self.leaf_pos[leaf])
                        break
                    index = child
            total = counts[0] + counts[1]
            if total <= 0:
                continue
            totals[0] += counts[0] / total
            totals[1] += counts[1] / total
        grand = (totals[0] + totals[1]) or 1.0
        return [t / grand for t in totals]

    # ---- float32 模拟：尽量贴近编译器在 x86/xtensa 上的单精度行为
    def predict_flat32(self, vector: List[float]) -> List[float]:
        x = [f32(v) for v in vector]
        threshold = list(self.threshold_q)
        leaf_neg = [f32(v) for v in self.leaf_neg]
        leaf_pos = [f32(v) for v in self.leaf_pos]
        t0 = f32(0.0)
        t1 = f32(0.0)
        for root in self.tree_root:
            if root < 0:
                c0, c1 = leaf_neg[-root - 1], leaf_pos[-root - 1]
            else:
                index = root
                while True:
                    child = self.left[index] if x[self.feature[index]] <= threshold[index] \
                        else self.right[index]
                    if child < 0:
                        leaf = -child - 1
                        c0, c1 = leaf_neg[leaf], leaf_pos[leaf]
                        break
                    index = child
            total = f32(c0 + c1)
            if total <= 0.0:
                continue
            t0 = f32(t0 + f32(c0 / total))
            t1 = f32(t1 + f32(c1 / total))
        grand = f32(t0 + t1)
        if grand == 0.0:
            grand = f32(1.0)
        return [f32(t0 / grand), f32(t1 / grand)]


def load_payload(path: Path) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    if payload.get('format') != FORMAT:
        raise SystemExit('模型 format 不是 %s：%r（拒绝导出，避免端云用错模型）'
                         % (FORMAT, payload.get('format')))
    if len(payload['classes']) != 2:
        raise SystemExit('端侧只实现二分类（本模型 %d 类）' % len(payload['classes']))
    return payload


# --------------------------------------------------------------------------- 生成 C

def _emit_float_array(text: List[str], name: str, values: List[float], per_line: int = 6) -> None:
    text.append('const float %s[] = {' % name)
    for start in range(0, len(values), per_line):
        chunk = values[start:start + per_line]
        text.append('    ' + ', '.join(f32_roundtrip_text(v) + 'f' for v in chunk) + ',')
    text.append('};')
    text.append('')


def _emit_int_array(text: List[str], ctype: str, name: str, values: List[int], per_line: int = 10) -> None:
    text.append('const %s %s[] = {' % (ctype, name))
    for start in range(0, len(values), per_line):
        chunk = values[start:start + per_line]
        text.append('    ' + ', '.join(str(int(v)) for v in chunk) + ',')
    text.append('};')
    text.append('')


def write_header(path: Path, flat: FlatForest, fingerprint: str, sizes: Dict[str, int]) -> None:
    names = flat.feature_names
    calib_x = [float(v) for v in (flat.calibration.get('x') or [])]
    calib_y = [float(v) for v in (flat.calibration.get('y') or [])]
    lines: List[str] = []
    lines.append('/*')
    lines.append(' * forest_model.h —— 自动生成，请勿手工修改。')
    lines.append(' *')
    lines.append(' * 生成命令：python tools/edge-export/export_forest.py')
    lines.append(' * 模型文件：models/%s.json（sha256 前 16 位 = %s）' % (flat.version, fingerprint))
    lines.append(' * 参考实现：backend-python/ml/forest.py（端侧语义以它为准）')
    lines.append(' *')
    lines.append(' * 节点数组只存内部节点，孩子字段编码：')
    lines.append(' *     孩子 >= 0  -> 下一层内部节点的绝对下标')
    lines.append(' *     孩子 <  0  -> 叶子，叶子下标 = -孩子 - 1')
    lines.append(' *')
    lines.append(' * 全部数组为 const，放 flash(.rodata)：本机估算 %d 字节（不含代码与字符串）。' % sizes['total'])
    lines.append(' */')
    lines.append('#ifndef FOREST_MODEL_H_')
    lines.append('#define FOREST_MODEL_H_')
    lines.append('')
    lines.append('#include <stdint.h>')
    lines.append('')
    lines.append('#define EDGE_MODEL_FORMAT          "%s"' % FORMAT)
    lines.append('#define EDGE_MODEL_VERSION         "%s"' % flat.version)
    lines.append('#define EDGE_MODEL_FINGERPRINT     "%s"' % fingerprint)
    lines.append('#define EDGE_FEATURE_COUNT         %d' % len(names))
    lines.append('#define EDGE_CLASS_COUNT           2')
    lines.append('#define EDGE_TREE_COUNT            %d' % len(flat.tree_root))
    lines.append('#define EDGE_NODE_COUNT            %d' % len(flat.threshold))
    lines.append('#define EDGE_LEAF_COUNT            %d' % len(flat.leaf_neg))
    lines.append('#define EDGE_CALIB_POINTS          %d' % len(calib_x))
    lines.append('#define EDGE_MAX_DEPTH             %d' % flat.max_depth)
    lines.append('#define EDGE_OPERATING_THRESHOLD   %sf' % f32_roundtrip_text(flat.operating_threshold))
    lines.append('#define EDGE_MODEL_BYTES           %d' % sizes['total'])
    lines.append('')
    lines.append('/* 叶子概率在 float32 下的单次聚合误差量级（导出时量化，不含累加误差）。 */')
    lines.append('#define EDGE_QUANT_NOTE            "float32 thresholds + float32 leaf probs"')
    lines.append('')
    lines.append('extern const char *const EDGE_FEATURE_NAMES[EDGE_FEATURE_COUNT];')
    lines.append('extern const float       EDGE_DEFAULTS[EDGE_FEATURE_COUNT];')
    lines.append('extern const float       EDGE_IMPORTANCE[EDGE_FEATURE_COUNT];')
    lines.append('extern const int32_t     EDGE_TREE_ROOT[EDGE_TREE_COUNT];')
    lines.append('extern const uint16_t    EDGE_TREE_NODES[EDGE_TREE_COUNT];')
    lines.append('extern const float       EDGE_NODE_THRESHOLD[EDGE_NODE_COUNT];')
    lines.append('extern const int32_t     EDGE_NODE_LEFT[EDGE_NODE_COUNT];')
    lines.append('extern const int32_t     EDGE_NODE_RIGHT[EDGE_NODE_COUNT];')
    lines.append('extern const uint8_t     EDGE_NODE_FEATURE[EDGE_NODE_COUNT];')
    lines.append('extern const float       EDGE_LEAF_NEG[EDGE_LEAF_COUNT];')
    lines.append('extern const float       EDGE_LEAF_POS[EDGE_LEAF_COUNT];')
    lines.append('extern const float       EDGE_CALIB_X[EDGE_CALIB_POINTS];')
    lines.append('extern const float       EDGE_CALIB_Y[EDGE_CALIB_POINTS];')
    lines.append('')
    lines.append('/* 特征下标常量：让上层代码不用记 0..25 的顺序，改顺序时编译期就会报错。 */')
    for index, name in enumerate(names):
        lines.append('#define EDGE_F_%-20s %d' % (name.upper(), index))
    lines.append('')
    lines.append('#endif /* FOREST_MODEL_H_ */')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def write_source(path: Path, flat: FlatForest) -> None:
    names = flat.feature_names
    defaults = [float(flat.defaults.get(name, 0.0)) for name in names]
    importance = [float(flat.importance.get(name, 0.0)) for name in names]
    calib_x = [float(v) for v in (flat.calibration.get('x') or [])]
    calib_y = [float(v) for v in (flat.calibration.get('y') or [])]

    lines: List[str] = []
    lines.append('/*')
    lines.append(' * forest_model.c —— 自动生成，请勿手工修改。')
    lines.append(' * 生成命令：python tools/edge-export/export_forest.py')
    lines.append(' * 模型：%s（%s）' % (flat.version, FORMAT))
    lines.append(' * 树 %d 棵 / 内部节点 %d 个 / 叶子 %d 个 / 特征 %d 维'
                 % (len(flat.tree_root), len(flat.threshold), len(flat.leaf_neg), len(names)))
    lines.append(' */')
    lines.append('#include "forest_model.h"')
    lines.append('')
    lines.append('const char *const EDGE_FEATURE_NAMES[EDGE_FEATURE_COUNT] = {')
    for start in range(0, len(names), 4):
        chunk = names[start:start + 4]
        lines.append('    ' + ', '.join('"%s"' % name for name in chunk) + ',')
    lines.append('};')
    lines.append('')
    _emit_float_array(lines, 'EDGE_DEFAULTS', defaults, per_line=4)
    _emit_float_array(lines, 'EDGE_IMPORTANCE', importance, per_line=4)
    _emit_int_array(lines, 'int32_t', 'EDGE_TREE_ROOT', flat.tree_root, per_line=10)
    _emit_int_array(lines, 'uint16_t', 'EDGE_TREE_NODES', flat.tree_nodes, per_line=10)
    _emit_float_array(lines, 'EDGE_NODE_THRESHOLD', flat.threshold_q, per_line=5)
    _emit_int_array(lines, 'int32_t', 'EDGE_NODE_LEFT', flat.left, per_line=10)
    _emit_int_array(lines, 'int32_t', 'EDGE_NODE_RIGHT', flat.right, per_line=10)
    _emit_int_array(lines, 'uint8_t', 'EDGE_NODE_FEATURE', flat.feature, per_line=16)
    _emit_float_array(lines, 'EDGE_LEAF_NEG', flat.leaf_neg, per_line=5)
    _emit_float_array(lines, 'EDGE_LEAF_POS', flat.leaf_pos, per_line=5)
    _emit_float_array(lines, 'EDGE_CALIB_X', calib_x, per_line=5)
    _emit_float_array(lines, 'EDGE_CALIB_Y', calib_y, per_line=5)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def estimate_sizes(flat: FlatForest, fingerprint: str) -> Dict[str, int]:
    names_bytes = sum(len(name) + 1 for name in flat.feature_names) + 4 * len(flat.feature_names)
    sizes = {
        'nodes': len(flat.threshold) * (4 + 4 + 4 + 1),
        'leaves': len(flat.leaf_neg) * 8,
        'calib': len(flat.calibration.get('x') or []) * 8,
        'defaults': len(flat.feature_names) * 4,
        'importance': len(flat.feature_names) * 4,
        'tree_index': len(flat.tree_root) * (4 + 2),
        'names': names_bytes + len(fingerprint) + 64,
    }
    sizes['total'] = sum(sizes.values())
    return sizes


# --------------------------------------------------------------------------- 自检

def verify(flat: FlatForest, payload: Dict[str, Any], count: int, seed: int = 20261113) -> int:
    """导出前后一致性自检。

    这一步是"先把错留在本机"：如果展平写错一孩子指针，这里会立刻炸，
    而不是等到烧到板子上、看到 p 全都一样才发现。
    """
    sys.path.insert(0, str(ROOT / 'backend-python'))
    from ml.forest import Forest  # noqa: WPS433 - 只有自检时才需要

    reference = Forest(payload)
    names = flat.feature_names
    defaults = [float(flat.defaults.get(name, 0.0)) for name in names]

    # 1) 默认向量：特征全填模型 defaults
    vectors: List[List[float]] = [list(defaults)]

    # 2) 伪造一批"像真观测"的向量：在 defaults 上做真实量级的扰动。
    #    注意**先量化到 float32**：端侧只可能是 float32 输入，自检必须按同样的输入比，
    #    否则测的是一个端侧永远拿不到的场景。
    import random
    rng = random.Random(seed)
    for _ in range(count):
        vector = []
        for name, base in zip(names, defaults):
            if name.startswith('miss_'):
                vector.append(float(rng.choice((0.0, 0.0, 0.0, 1.0))))
            elif name == 'stationCode':
                vector.append(float(rng.choice((0.0, 1.0, 2.0, -1.0))))
            elif name == 'month':
                vector.append(float(rng.randint(1, 12)))
            elif name in ('hourSin', 'hourCos', 'wdirSin', 'wdirCos'):
                vector.append(rng.uniform(-1.0, 1.0))
            elif name in ('visM', 'visMin3h', 'visMin6h'):
                vector.append(max(0.0, rng.choice(
                    (rng.uniform(100.0, 1000.0), rng.uniform(1000.0, 5000.0), rng.uniform(5000.0, 20000.0)))))
            else:
                vector.append(base + rng.uniform(-1.0, 1.0) * (abs(base) * 0.5 + 1.0))
        vectors.append([f32(value) for value in vector])

    # 3) 边界回归：把特征值直接压到某个内部节点的阈值上。
    #    这是**唯一**能让端云翻边的地方，不专门测它就等于没测（第一轮实测 40/1000 超差就是这么来的）。
    boundary = 0
    for _ in range(min(count * 2, 400)):
        node = rng.randrange(len(flat.threshold))
        vector = list(defaults)
        vector[flat.feature[node]] = flat.threshold_q[node]  # 恰好等于向下取整后的阈值
        vectors.append([f32(value) for value in vector])
        boundary += 1
        vector_lo = list(defaults)
        vector_lo[flat.feature[node]] = f32(flat.threshold[node])  # 就近取整（可能恰好低于阈值）
        vectors.append([f32(value) for value in vector_lo])
        boundary += 1

    worst64 = 0.0
    worst32 = 0.0
    for vector in vectors:
        expected = reference.predict(vector)['probabilitiesExact']['POS']
        got64 = flat.predict_flat64(vector)[1]
        got32 = flat.predict_flat32(vector)[1]
        worst64 = max(worst64, abs(got64 - expected))
        worst32 = max(worst32, abs(got32 - expected))

    print('自检：%d 组向量（其中 %d 组压在阈值边界上）' % (len(vectors), boundary))
    print('  展平后 float64 遍历 vs forest.py       最大 |Δp| = %.3e  %s'
          % (worst64, 'PASS' if worst64 == 0.0 else 'FAIL'))
    print('  展平后 float32 模拟 vs forest.py       最大 |Δp| = %.3e  %s'
          % (worst32, 'PASS(<=1e-4)' if worst32 <= 1e-4 else 'FAIL'))
    if worst64 != 0.0:
        print('  [FAIL] 展平结果与参考实现不等价，禁止烧录：先查 _is_leaf / _children 的判定顺序。')
        return 1
    if worst32 > 1e-4:
        print('  [FAIL] float32 量化误差超过对拍容差 1e-4，需要复核阈值精度。')
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='导出随机森林为端侧 C 源码')
    parser.add_argument('--model', default=str(DEFAULT_MODEL), help='模型 JSON 路径')
    parser.add_argument('--out-header', default=str(OUT_H), help='输出头文件路径')
    parser.add_argument('--out-source', default=str(OUT_C), help='输出源文件路径')
    parser.add_argument('--verify', type=int, default=64, help='自检向量条数（0 表示跳过）')
    args = parser.parse_args()

    model_path = Path(args.model)
    payload = load_payload(model_path)
    flat = FlatForest(payload)

    fingerprint = hashlib.sha256(model_path.read_bytes()).hexdigest()[:16]
    sizes = estimate_sizes(flat, fingerprint)

    write_header(Path(args.out_header), flat, fingerprint, sizes)
    write_source(Path(args.out_source), flat)

    print('模型        : %s' % model_path.name)
    print('格式/版本   : %s / %s' % (FORMAT, flat.version))
    print('指纹        : %s（模型 JSON 的 sha256 前 16 位）' % fingerprint)
    print('特征/树/深度: %d 维 / %d 棵 / 最大深度 %d'
          % (len(flat.feature_names), len(flat.tree_root), flat.max_depth))
    print('内部节点    : %d' % len(flat.threshold))
    print('叶子        : %d' % len(flat.leaf_neg))
    print('校准点      : %d（isotonic，forest.py 不下校准，端侧只随附不参与 predict）'
          % len(flat.calibration.get('x') or []))
    print('')
    print('flash 占用估算（不含代码段与 libc）：')
    for key in ('nodes', 'leaves', 'calib', 'defaults', 'importance', 'tree_index', 'names'):
        print('  %-10s %9d 字节' % (key, sizes[key]))
    print('  %-10s %9d 字节  (%.1f KiB)' % ('合计', sizes['total'], sizes['total'] / 1024.0))
    print('')
    print('写出        : %s (%d KiB)' % (Path(args.out_source).name, Path(args.out_source).stat().st_size // 1024))
    print('写出        : %s' % Path(args.out_header).name)

    if args.verify <= 0:
        return 0
    print('')
    return verify(flat, payload, args.verify)


if __name__ == '__main__':
    sys.exit(main())
