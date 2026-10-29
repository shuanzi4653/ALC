# -*- coding: utf-8 -*-
"""两份规则文件必须语义等价：`config/rules-v1.json` ↔ classpath 副本。

Why this exists
---------------
阈值被复制成两份：一份是工程根的 `config/rules-v1.json`（外部配置，运维可改），
一份是 `backend-java/src/main/resources/rules-v1.json`（打进 jar 的 classpath 副本，
外部文件缺失时回落）。`RuleProperties` 的优先级是 **外部 → classpath → 内置默认**。

2026-10-17 实测两份**不等**，而且差的地方恰好是一处静默失效：

    classpath 副本里 `thunderProb` 少了 `required: false`

Java 侧 `required` 的默认值**是 true**。于是"回落到 classpath 副本"这个动作，
把雷暴概率从"可选要素"变成"必需字段"—— 而 open-meteo 根本不发布这个字段。
结果是**每一轮都以「缺字段」被拒**，界面上表现为"监测一直失败"，
而规则文件本身看起来完全正常（阈值全对）。

这条缝隙为什么没有任何既有判据能看见：

  * Python 侧只读外部文件，永远读不到副本 —— 它的测试全绿；
  * Java 侧单测直接构造 `RuleSpec`，不经过 `RuleProperties` 的回落路径；
  * 打包把副本塞进 jar 而不比较它；
  * 部署后只有在外部文件**恰好缺失**时才触发，而那不是常规路径。
  ⇒ 四个环节各自都对，缺的是"这两份文件是不是同一份"这一问。

What it checks
--------------
**语义**等价，不是字节相同：解析成对象后深比较。缩进/键序/文件末尾换行不同不算失败
（否则每次格式化都要动这个闸门），但任何一个**影响判定的字段**不同都算失败 ——
包括 `required`、`penaltyWarn`、`displayMultiplier`、`displayDivisor` 这些
"看起来只是展示"、实际会改变 SFI 或分档结果的键。

失败时逐路径打印，不只说"不相等"：`factors[4].required: 缺失 vs False` 这种定位，
比"两份文件不一致"能直接指到该改哪一行。

Run:  python tools/maintenance/_verify_rules_parity.py [--self-test]
Exit: 0 等价 / 1 不等价 / 2 文件缺失或不可解析
"""

import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXTERNAL = os.path.join(ROOT, 'config', 'rules-v1.json')
CLASSPATH = os.path.join(ROOT, 'backend-java', 'src', 'main', 'resources', 'rules-v1.json')

MISSING = object()


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def diff(a, b, path=''):
    """返回差异行列表。`a` = 外部（基准），`b` = classpath 副本。"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            sub = '%s.%s' % (path, key) if path else str(key)
            if key not in a:
                out.append('%s: 外部缺失，副本有 %r' % (sub, b[key]))
            elif key not in b:
                out.append('%s: 副本缺失（外部为 %r）' % (sub, a[key]))
            else:
                out.extend(diff(a[key], b[key], sub))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append('%s: 长度 %d vs %d' % (path or '<root>', len(a), len(b)))
        for i in range(min(len(a), len(b))):
            out.extend(diff(a[i], b[i], '%s[%d]' % (path, i)))
        return out
    if a != b:
        out.append('%s: %r vs %r' % (path or '<root>', a, b))
    return out


def required_without_default(doc):
    """列出"依赖 required 默认值"的要素 —— 这就是那次静默失效的形状。

    单独查这一项，是因为它的失败方式与"阈值写错"完全不同：阈值写错会让结果变化，
    `required` 写成默认 true 会让**整轮被拒**。两种症状在界面上都很像"服务没数据"。
    """
    hits = []
    for i, factor in enumerate(doc.get('factors') or []):
        key = factor.get('key')
        if key in ('thunderProb',):
            if 'required' not in factor:
                hits.append('factors[%d].%s 未显式写 required（Java 默认 true）' % (i, key))
            elif factor.get('required') is not False:
                hits.append('factors[%d].%s 的 required 不是 false（当前 %r）'
                            % (i, key, factor.get('required')))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true', help='负向自检：造一份少了 required 的副本，必须报错')
    ap.add_argument('--external', default=EXTERNAL)
    ap.add_argument('--classpath', default=CLASSPATH)
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    for path in (args.external, args.classpath):
        if not os.path.isfile(path):
            print('[FAIL] 规则文件不存在：%s' % path)
            return 2
    try:
        ext = load(args.external)
        cls = load(args.classpath)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print('[FAIL] 规则文件不可解析：%s' % exc)
        return 2

    problems = []
    problems.extend(diff(ext, cls))
    problems.extend(required_without_default(cls))

    if problems:
        print('[FAIL] 两份规则文件不等价（外部 → 副本）：')
        for line in problems:
            print('  - %s' % line)
        print('  修法：cp config/rules-v1.json backend-java/src/main/resources/rules-v1.json')
        return 1

    print('[PASS] 两份规则文件语义等价：%d 个要素，version=%s'
          % (len(ext.get('factors') or []), ext.get('version')))
    return 0


def self_test():
    """负向自检：把真文件造出三种已知差异，判据必须每一种都报出来。

    只验"正确的东西通过"不算验过 —— 那样连"程序只会 print PASS"都能过。
    """
    ext = load(EXTERNAL)
    ok = True

    cases = []

    # ① 去掉 required: false —— 就是 2026-10-17 实测的那个真实缺陷
    broken = copy.deepcopy(ext)
    for f in broken['factors']:
        if f.get('key') == 'thunderProb':
            f.pop('required', None)
    cases.append(('缺 required', broken, 'required'))

    # ② 改一个阈值
    broken2 = copy.deepcopy(ext)
    for f in broken2['factors']:
        if f.get('key') == 'windSpeed':
            f['banValue'] = 99
    cases.append(('阈值被改', broken2, 'banValue'))

    # ③ 删一个要素
    broken3 = copy.deepcopy(ext)
    broken3['factors'] = [f for f in broken3['factors'] if f.get('key') != 'visibilityM']
    cases.append(('要素缺失', broken3, 'visibilityM'))

    for name, doc, needle in cases:
        lines = list(diff(ext, doc)) + list(required_without_default(doc))
        hit = any(needle in line for line in lines)
        print('%s  负向用例「%s」→ %s' % ('ok  ' if hit else 'FAIL', name,
                                         '已报出' if hit else '**没报出来**'))
        ok = ok and hit

    # ④ 正向用例：真副本必须通过（否则判据永远报红，等于没有）
    same = load(CLASSPATH)
    lines = list(diff(ext, same)) + list(required_without_default(same))
    print('%s  正向用例「真副本」→ %s' % ('ok  ' if not lines else 'FAIL',
                                         '等价' if not lines else '**误报 %d 条**' % len(lines)))
    ok = ok and not lines

    print('self-test %s' % ('PASSED' if ok else 'FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
