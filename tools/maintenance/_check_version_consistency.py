"""Five landing points must agree with `VERSION`; the prose must name the same version.

Why this exists
---------------
`0.9.35（Beta）` 那一轮升级时，五个程序落点都改了、所有闸门都是绿的，而
`README.md` 的标题与 `docs/NAMING.md` §7 正文**都还写着 `0.9.33（Beta）`**。
它没有被任何判据读到：闸门查的是代码形状、链接、计数，**没有一条在读"当前是哪个版本"**。
于是"版本号改完了"这句话的真实含义只剩下"我记得我改了"。

本文件就是那条判据。它读**一处事实**（`VERSION`）然后逐处核对**引用它的地方**：

  1. `VERSION` 本身是合法 semver（`x.y.z-beta`），不是全角括号写法；
  2. `backend-java/pom.xml` 的项目版本（且不得再有一个**别的** semver 版本串顶着）；
  3. `frontend/package.json`；
  4. `frontend/package-lock.json` **两处**（`version` 与 `packages[""].version`）；
  5. `backend-python/traffic/weather_sources.py` 的 `User-Agent`（对外标识，改版本时要跟着走）；
  6. `README.md` 首行与 `docs/NAMING.md` 正文里的**文档写法** `x.y.z（Beta）`。

出口三态（**不许把两种失败混成一个**，见 `changelog/ISSUES.md` M60）：

      exit 0  全部一致
      exit 1  量出来了，有 N 处不一致（逐条打印"哪个文件、写的是什么、应当是什 么"）
      exit 2  无法测量（缺文件 / 读不动 / 正则一条都没命中）—— 这一种**不是**不一致

`--self-test` 用**内存里的假文件**做三负一正，证明这个检查器咬得住：不碰磁盘、不改真文件。
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 两条合法形态：预发布 `x.y.z-beta`（程序落点写这个），正式版 `x.y.z`（V1.0.0 起）。
# 全角括号的写法只属于散文，程序里出现就是 M60 那类"看起来改完了"。
SEMVER = re.compile(r'^\d+\.\d+\.\d+(-beta)?$')
# 本文件**刻意不**用正则在 pom 里找"所有 semver" —— 见 audit() 第 2 段那段注释：
# 那会连 `<parent>` 与插件版本一起命中（Spring Boot 3.5.6 就一直在这份文件里）。

FILES = {
    'version': 'VERSION',
    'pom': 'backend-java/pom.xml',
    'pkg': 'frontend/package.json',
    'lock': 'frontend/package-lock.json',
    'ua': 'backend-python/traffic/weather_sources.py',
    'readme': 'README.md',
    'naming': 'docs/NAMING.md',
}


def load(root=ROOT):
    """Read every file this check needs, or return ``None`` with a reason."""
    texts = {}
    for key, rel in FILES.items():
        path = os.path.join(root, rel)
        try:
            with io.open(path, encoding='utf-8') as handle:
                texts[key] = handle.read()
        except OSError as error:
            return None, 'cannot read %s: %s' % (rel, error)
    return texts, None


def _doc_form(semver):
    """程序里的版本 → 文档里怎么写。

    `0.11.x-beta` 那一片写 `0.11.x（Beta）`；正式版（`1.0.0`）写 `V1.0.0` ——
    用户 2026-10-27 把产品版本正式定为 `V1.0.0`，软著登记与产品版本从此**同一个号**，
    不再存在两套编号互相对照的问题。
    """
    if semver.endswith('-beta'):
        return semver[:-5] + '（Beta）'
    return 'V' + semver


def audit(texts):
    """Return ``(findings, facts)``; ``findings`` empty means every landing point agrees."""
    findings = []
    facts = {}

    version = texts['version'].strip()
    facts['version'] = version
    if not SEMVER.match(version):
        findings.append('VERSION is %r, which is not x.y.z or x.y.z-beta '
                        '(the full-width 括号 form belongs in prose, never in program files)'
                        % version)
        # 版本串不合法时后面的比对没有意义 —— 但仍然把每一个落点的**现值**报出来，
        # 否则读者只知道"VERSION 写错了"，不知道还有哪些地方跟着错。
        facts['version'] = version
    doc = _doc_form(version)

    # --- 2. pom.xml ---------------------------------------------------------
    # 只认**项目自己的** `<version>`（`<project>` 的直接子元素）。正则数"所有 semver"
    # 会把 `<parent>`／插件的版本一起算进来 —— 例如 Spring Boot `3.5.6` —— 于是这条
    # 判据会常年红着报一个**完全正常**的东西（量错了对象，与 M61 同族）。
    #
    # 读直接子元素时必须**先剥命名空间**：本文件带 `xmlns=".../POM/4.0.0"`，
    # `root.find('version')` 在带默认命名空间的文档里恒为 `None` —— 那会让这条判据
    # 永远报"pom.xml project version is None"，看起来像 pom 坏了。
    pom_version = None
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(texts['pom'])
        for child in list(root):
            tag = child.tag.split('}')[-1]
            if tag == 'version':
                pom_version = (child.text or '').strip()
                break
    except Exception as error:                      # noqa: BLE001 - 报出来，不吞掉
        findings.append('pom.xml could not be parsed as XML: %s' % error)
    facts['pom'] = pom_version
    if pom_version != version:
        findings.append('pom.xml project version is %r, but VERSION says %r'
                        % (pom_version, version))

    # --- 3/4. npm manifests -------------------------------------------------
    try:
        package = json.loads(texts['pkg'])
    except ValueError as error:
        findings.append('package.json is not valid JSON: %s' % error)
        package = {}
    facts['pkg'] = package.get('version')
    if package.get('version') != version:
        findings.append('package.json says %r, but VERSION says %r'
                        % (package.get('version'), version))

    try:
        lock = json.loads(texts['lock'])
    except ValueError as error:
        findings.append('package-lock.json is not valid JSON: %s' % error)
        lock = {}
    lock_root = lock.get('version')
    lock_pkg = ((lock.get('packages') or {}).get('') or {}).get('version')
    facts['lock'] = [lock_root, lock_pkg]
    for label, value in (('version', lock_root), ('packages[""].version', lock_pkg)):
        if value != version:
            findings.append('package-lock.json %s says %r, but VERSION says %r'
                            % (label, value, version))

    # --- 5. 对外 User-Agent -------------------------------------------------
    # 只取前三段（`x.y.z`）：UA 里不写 `-beta`，它标识的是"哪一代"而不是"哪个构建"。
    short = version.replace('-beta', '')
    token = 'tianchuang-alc/'
    match = re.search(re.escape(token) + r'([0-9][0-9A-Za-z.\-]*)', texts['ua'])
    facts['ua'] = match.group(1) if match else None
    if not match:
        findings.append('weather_sources.py has no %s<User-Agent version> token' % token)
    elif match.group(1) != short:
        findings.append('weather_sources.py User-Agent says %s%s, but VERSION says %s'
                        % (token, match.group(1), short))

    # --- 6. 散文里的"当前版本" ----------------------------------------------
    first_line = texts['readme'].split('\n', 1)[0]
    facts['readme_title'] = first_line.strip()
    if doc not in first_line:
        findings.append('README.md title does not name %s: %r' % (doc, first_line.strip()[:90]))
    if doc not in texts['naming']:
        findings.append('docs/NAMING.md never mentions %s (its §7 table is the '
                        'authority the rest of the docs copy from)' % doc)

    return findings, facts


def _self_test():
    """三负一正：内存里的假文件，不碰磁盘。"""
    base = {
        'version': '9.8.7-beta\n',
        'pom': '<project><version>9.8.7-beta</version></project>',
        'pkg': json.dumps({'version': '9.8.7-beta'}),
        'lock': json.dumps({'version': '9.8.7-beta',
                            'packages': {'': {'version': '9.8.7-beta'}}}),
        'ua': "UA = os.environ.get('X', 'tianchuang-alc/9.8.7 (low-altitude traffic research)')",
        'readme': '# 系统 9.8.7（Beta）\n',
        'naming': '当前为 **`9.8.7（Beta）`**。',
    }
    cases = []

    clean, _ = audit(base)
    cases.append(('正向：真副本', clean, None))

    mutated = dict(base, pom='<project><version>9.8.6-beta</version></project>')
    cases.append(('负向：pom 落后一版', audit(mutated)[0], 'pom.xml project version'))

    mutated = dict(base, lock=json.dumps({'version': '9.8.7-beta',
                                          'packages': {'': {'version': '9.8.6-beta'}}}))
    cases.append(('负向：lock 第二处没改', audit(mutated)[0], 'packages[""].version'))

    mutated = dict(base, readme='# 系统 9.8.6（Beta）\n')
    cases.append(('负向：README 标题落后', audit(mutated)[0], 'README.md title'))

    mutated = dict(base, ua="UA = 'tianchuang-alc/9.8.3 (x)'")
    cases.append(('负向：UA 没跟版本', audit(mutated)[0], 'User-Agent'))

    # 正式版形态（V1.0.0 起）：程序写 1.0.0、文档写 V1.0.0。
    # 没有这一条，`_doc_form` 改坏了也只会在真升级那天才发现 —— 那时已经晚了。
    stable = {
        'version': '1.0.0\n',
        'pom': '<project><version>1.0.0</version></project>',
        'pkg': json.dumps({'version': '1.0.0'}),
        'lock': json.dumps({'version': '1.0.0', 'packages': {'': {'version': '1.0.0'}}}),
        'ua': "UA = os.environ.get('X', 'tianchuang-alc/1.0.0 (low-altitude traffic research)')",
        'readme': '# 系统 V1.0.0\n',
        'naming': '当前为 **`V1.0.0`**。',
    }
    cases.append(('正向：正式版 V1.0.0', audit(stable)[0], None))
    mutated = dict(stable, readme='# 系统 0.11.27（Beta）\n')
    cases.append(('负向：正式版却写回 Beta 写法', audit(mutated)[0], 'README.md title'))

    failures = 0
    for label, problems, must_contain in cases:
        joined = ' | '.join(problems) if problems else ''
        if must_contain is None:
            if problems:
                print('FAIL %s -> should be clean, got: %s' % (label, joined))
                failures += 1
            else:
                print('ok %s -> 等价' % label)
            continue
        if must_contain not in joined:
            print('FAIL %s -> did not report %r (got: %s)'
                  % (label, must_contain, joined or 'nothing'))
            failures += 1
        else:
            print('ok %s -> 已报出' % label)

    print('self-test PASSED' if not failures else 'self-test FAILED (%d)' % failures)
    return 0 if not failures else 1


def main(argv):
    if '--self-test' in argv:
        return _self_test()

    texts, reason = load()
    if texts is None:
        print('cannot measure: %s' % reason)
        return 2

    findings, facts = audit(texts)
    print('version %s | pom %s | lock %s | ua %s'
          % (facts.get('version'), facts.get('pom'), facts.get('lock'), facts.get('ua')))
    if not findings:
        print('version consistency -- ok')
        return 0
    for item in findings:
        print('FAIL %s' % item)
    print('version consistency -- %d finding(s)' % len(findings))
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
