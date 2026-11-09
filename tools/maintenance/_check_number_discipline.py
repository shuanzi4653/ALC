"""交付材料里不许出现三个已作废的数字；出现即失败。

为什么要有这一条
----------------
`3 016`、`3 048`、`1 614` 这三个数在项目的不同阶段都"真过"，但它们的语义各不相同：

    3 016  某次会话的绕飞架次        （与最终口径 2 848 冲突，同一个量出现两个值）
    3 048  B 组处置架次              （被误当成"改判"讲，2640+408 只是凑数能凑出来）
    1 614  0.9.4 建网时的班次数      （旧口径，早就不成立了）

三条都不是"算错"，而是**同一个词在不同会话里指了不同的量**。它们在 `docs/0.11.*`
的历史记录里必须留着（那是当时的真相，删掉才是作假），但**交付材料正文里不能再出现** ——
评委问"这个数哪来的"，答不上来，整份材料的可信度就归零。

所以本闸门是一条**范围判据**：只查交付材料，不查历史记录；并且允许"正在讨论这个数"
的行（口径表、删除线、禁用说明）通过，因为那些行是在**说**它，不是在**用**它。

出口三态（与 `_check_version_consistency.py` 一致）：

    exit 0  交付材料层干净
    exit 1  量出来了，有 N 处不该出现的数字
    exit 2  无法测量（文档目录不存在 / 一个文件都没读到）—— 不是"通过"

`--self-test` 用内存假文件做三负一正，不碰磁盘。
"""

from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 交付材料：会被打印、截图、贴进方案与 PPT 的那些。
# 历史记录（docs/0.11.*、docs/天窗智巡_0.11.*、changelog/）刻意不在范围内 —— 见文件头。
MATERIAL_GLOBS = ('README.md', 'docs')
MATERIAL_PATTERNS = (
    re.compile(r'^V1\.0\.1-.*\.md$'),        # 口径册（含禁用示例，靠行级豁免）
    re.compile(r'^国赛方案-v3-.*\.md$'),      # 当前有效方案
    re.compile(r'^国赛版本构建.*\.md$'),
    re.compile(r'^硬件采购清单.*\.md$'),
)
# 明确排除：历史执行记录与过期稿（v2 已标"被取代"）。它们保留当时的真相，不做清理。
EXCLUDE = re.compile(r'^0\.\d|^天窗智巡_0\.\d|^国赛方案-v2|^盘点-|^国赛方案对比|^V1\.0\.1-.*-r1')

# 禁用数字：带空格与不带空格两种写法都要咬住（材料里两种都出现过）
FORBIDDEN = (
    ('3 016', re.compile(r'3[\s,，]?016')),
    ('3 048', re.compile(r'3[\s,，]?048')),
    ('1 614', re.compile(r'1[\s,，]?614')),
)

# "在说这个数"而不是"在用这个数"的行：删除线、禁用说明、以及**引用检查命令本身**的行。
# 最后一条很关键：口径册里那行 `grep -r "3 016\|3 048" docs/` 是在写判据，不是在用数字。
EXEMPT = re.compile(r'~~|禁用|清零|不得出现|作废|grep')


def _material_files(root=ROOT):
    """交付材料清单。只认白名单前缀，避免把历史记录扫进来。"""
    paths = []
    readme = os.path.join(root, 'README.md')
    if os.path.isfile(readme):
        paths.append(readme)
    docs = os.path.join(root, 'docs')
    if os.path.isdir(docs):
        for name in sorted(os.listdir(docs)):
            if not name.endswith('.md') or EXCLUDE.search(name):
                continue
            if not any(pattern.match(name) for pattern in MATERIAL_PATTERNS):
                continue
            paths.append(os.path.join(docs, name))
    return paths


def audit(files):
    """``files`` 是 ``[(相对路径, 文本)]``；返回 (findings, facts)。"""
    findings = []
    facts = {'files': len(files), 'hits': 0}
    for rel, text in files:
        for lineno, line in enumerate(text.splitlines(), 1):
            if EXEMPT.search(line):
                continue
            for label, pattern in FORBIDDEN:
                if pattern.search(line):
                    facts['hits'] += 1
                    findings.append('%s:%d 出现已作废的 %s —— %s'
                                    % (rel, lineno, label, line.strip()[:80]))
    return findings, facts


def load(root=ROOT):
    files = []
    for path in _material_files(root):
        try:
            with io.open(path, encoding='utf-8') as handle:
                files.append((os.path.relpath(path, root).replace('\\', '/'), handle.read()))
        except OSError as error:
            return None, 'cannot read %s: %s' % (path, error)
    if not files:
        return None, 'no material files under %s/docs' % root
    return files, None


def _self_test():
    cases = []
    clean = [('README.md', '# 系统\n放行率 94%，绕飞 2 848 架次。\n')]
    cases.append(('正向：五个规范数字', audit(clean)[0], None))

    plain = [('docs/方案.md', '改判 3048 架次，暴露 −3016。\n')]
    cases.append(('负向：正文直接用了禁用数字', audit(plain)[0], '已作废的 3 048'))

    spaced = [('docs/方案.md', '绕飞 3 016 架。\n')]
    cases.append(('负向：带空格写法也要咬住', audit(spaced)[0], '已作废的 3 016'))

    old = [('README.md', '建网 1614 班。\n')]
    cases.append(('负向：旧口径 1 614', audit(old)[0], '已作废的 1 614'))

    exempt = [('docs/V1.0.1-软件与材料.md', '| ~~3 048~~ | 处置架次 | ❌ 全文清零 |\n')]
    cases.append(('正向：口径表里作为禁用示例出现', audit(exempt)[0], None))

    failures = 0
    for label, problems, must_contain in cases:
        joined = ' | '.join(problems) if problems else ''
        if must_contain is None:
            if problems:
                print('FAIL %s -> 应为干净，却报：%s' % (label, joined))
                failures += 1
            else:
                print('ok %s -> 放行' % label)
            continue
        if must_contain not in joined:
            print('FAIL %s -> 没报出 %r（实际：%s）'
                  % (label, must_contain, joined or 'nothing'))
            failures += 1
        else:
            print('ok %s -> 已报出' % label)
    print('self-test PASSED' if not failures else 'self-test FAILED (%d)' % failures)
    return 0 if not failures else 1


def main(argv):
    if '--self-test' in argv:
        return _self_test()
    files, reason = load()
    if files is None:
        print('cannot measure: %s' % reason)
        return 2
    findings, facts = audit(files)
    print('material files %d | forbidden hits %d' % (facts['files'], facts['hits']))
    if not findings:
        print('number discipline -- ok')
        return 0
    for item in findings:
        print('FAIL %s' % item)
    print('number discipline -- %d finding(s)' % len(findings))
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
