# -*- coding: utf-8 -*-
"""C-1（0.11.3）：把「算法身份常显在导航栏」这条旧契约改成「收进复现参数折叠区」。

用正则而不是整段字面量：这几条 test 的标题里带着中文引号，逐字抄写极易在
引号字形上错一个字符，而错法的表现是"锚点不存在"——那还算好的；更坏的是
抄成了另一条相似的断言，改完看着绿、其实没改对。
"""
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'tests' / 'algorithmIdentity.test.mjs'
text = PATH.read_text(encoding='utf-8')

# 1) 标题：导航栏常显 → 复现参数折叠区
text, n1 = re.subn(r"test\('组件把算法身份渲染在导航栏常显区'",
                   "test('组件把算法身份渲染在「复现参数」折叠区（0.11.3 起不再常显于导航栏）'",
                   text, count=1)

# 2) 落点断言：nav → details.traffic-repro，并加一条反向判据
old_nav = re.search(r"\n  const nav = /<nav class=\"operations-nav\".*?缺少悬停说明'\)\n", text, re.S)
if old_nav is None:
    raise SystemExit('找不到落点断言块')
new_nav = """
  // C-1：位置从导航栏改到「工程信息 · 复现参数」。判据仍是"确实被渲染出来"，
  // 只是落点跟着产品决策一起搬 —— 断言留在旧位置，就是一条假的回归红灯。
  const repro = /<details class="traffic-repro"[\\s\\S]*?<\\/details>/.exec(template)?.[0] ?? ''
  assert.ok(repro, '找不到复现参数折叠区')
  assert.match(repro, /data-algorithm-identity/, '标识没有挂进复现参数折叠区')
  assert.match(repro, /\\{\\{algorithmIdentityLabel\\}\\}/, '算了身份却没有渲染，等于没有')
  assert.match(repro, /:title="algorithmIdentityNote"/, '缺少悬停说明')
  // 反向判据：它**不许**再出现在导航栏常显区 —— 两处各说一次，改一处漏一处。
  const nav = /<nav class="operations-nav"[\\s\\S]*?<\\/nav>/.exec(template)?.[0] ?? ''
  assert.doesNotMatch(nav, /data-algorithm-identity/,
    '算法标识又回到导航栏了 —— 工程字段不进主界面（C-1）')
"""
text = text[:old_nav.start()] + new_nav + text[old_nav.end():]

# 3) 「常显」那条 test：整条替换成"默认折叠、工程档展开"
block = re.search(r"test\('标识是常显的.*?\n\}\)\n", text, re.S)
if block is None:
    raise SystemExit('找不到常显 test 块')
new_block = """test('复现参数默认折叠，工程密度档下默认展开（C-1 之后的可达性判据）', () => {
  // 旧契约是"标识常显"，新落点是一个 <details>。折叠区最容易出的错是
  // "必须先点一下"变成"默认状态下不存在"，所以这里钉住它的开合由密度档决定。
  // 工程档必须默认展开：需要看指纹的人，恰恰是在排障。
  const repro = /<details class="traffic-repro"[^>]*>/.exec(template)?.[0] ?? ''
  assert.ok(repro, '找不到复现参数折叠区')
  assert.match(repro, /:open="densityPolicy\\(density\\)\\.engineering"/,
    '复现参数的开合必须挂在密度档上：工程档默认展开，其余默认收起')
})
"""
text = text[:block.start()] + new_block + text[block.end():]

# 4) 只出现一次：标题改名，判据不变
text, n4 = re.subn(r"test\('导航栏标识只出现一次'", "test('算法标识在模板里只出现一次'", text, count=1)

PATH.write_text(text, encoding='utf-8')
print('patched: title=%d nav=%d once=%d' % (n1, 1, n4))
