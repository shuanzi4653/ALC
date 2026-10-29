# -*- coding: utf-8 -*-
"""W-18（0.11.4）：研判覆盖率的文案与提示。不碰计数逻辑。

真因：`ask()` 里 `askedFor = props.selected?.id || ''`，未选班次时为空串，
于是不登记（有意设计：全域问答无法归属到某一班）。界面从来没说这件事，
所以看起来是「研判成功了但一次都没研判过」。
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'components' / 'OperationsConsole.vue'
text = PATH.read_text(encoding='utf-8')

# 1) 记录本次是否全域
old = ("const question=ref('当前运行有哪些风险，为什么需要绕行或暂停？'),"
       "answer=ref(null),asking=ref(false),error=ref('')")
new = (old + "\n"
       "// 0.11.4（W-18）：记下**这一次**问的是不是全域。覆盖率只登记挂在班次上的研判，\n"
       "// 全域提问必然不登记 —— 界面原来从没说这件事，于是看起来像计数器坏了。\n"
       "const lastGlobal=ref(false)")
if old not in text:
    raise SystemExit('answer 声明锚点不存在')
text = text.replace(old, new, 1)

# 2) ask() 里赋值
old = "  const askedFor=props.selected?.id||''"
if old not in text:
    raise SystemExit('askedFor 锚点不存在')
text = text.replace(old, old + "\n  lastGlobal.value=!askedFor", 1)

# 3) 按钮文案随选中态
old = "{{asking?'正在查证…':'查证并研判'}}"
if old not in text:
    raise SystemExit('按钮文案锚点不存在')
text = text.replace(old, "{{asking?'正在查证…':(selected?'查证并研判':'查证并研判（全域）')}}", 1)

# 4) 结果卡前加提示
old = '  <p v-if="!answer" class="operations-muted">研判只引用当前计划已有的证据'
if old not in text:
    raise SystemExit('结果卡锚点不存在')
note = ('  <p v-if="answer&&lastGlobal" class="operations-muted" data-global-note>'
        '<b>本次为全域提问</b>：没有挂在具体班次上，因此<b>不计入</b>下方「研判覆盖」。'
        '要让它进入覆盖统计，先在列表里选一个班次再问。'
        '这不是失败 —— 全域问答的结论无法归属到某一班，登记它等于给一个不存在的结论盖标记。</p>\n')
text = text.replace(old, note + old, 1)

# 5) 覆盖率卡片补分母说明
old = ('<p>本会话已对 <b>{{coverage.reviewed}}</b> 个班次发起过研判，'
       '尚有 <b>{{coverage.uncovered}}</b> 个未研判')
if old not in text:
    raise SystemExit('覆盖率文案锚点不存在')
text = text.replace(old, ('<p>分母是全部 <b>{{coverage.total}}</b> 班；'
                          '<b>全域提问不计入</b>。已对 <b>{{coverage.reviewed}}</b> 个班次发起过研判，'
                          '尚有 <b>{{coverage.uncovered}}</b> 个未研判'), 1)

PATH.write_text(text, encoding='utf-8')
print('W-18 patched')
