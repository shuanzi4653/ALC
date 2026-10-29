# -*- coding: utf-8 -*-
"""0.11.7 · F-1：让「气象通道」这个开关真的能按。

## 这个死锁是我上一轮（E-3）自己做出来的

`api.js` 里写了 `setOperatorRole()`，**但全站 0 个调用方** ⇒ `localStorage['alc-operator']`
永远是默认 `duty` ⇒ 切 `weather-mode`（需 admin）恒 403 ⇒ 页面上那个按钮焊死。

今天第 4 次同形问题（前三次：`verdictTone` / `scheduleRelayRetry` / `paintFogCircles`）。
共同点：**函数写完了，没有入口**。

## 两处改动

### ① 后端：往"更不可信"要权限，往"更可信"不要

现在切**进去**和切**回来**都要 admin —— 于是一旦用 admin 切到虚拟气象，普通用户
在页面上再也切不回来。这是单向门。

改成：

    进虚拟态 = admin（它会让全场结论变成模拟的）
    回实测态 = observer（任何人 —— 安全侧必须永远可恢复）

方案原来写的"虚拟态 30 分钟内允许任何人切回"是**同一个错误换了个触发条件**：
30 分钟之后就又回到"无人能恢复"。不设时限。

### ② 前端：设置面板加一个真的身份切换器

`设置 → 操作员角色`，三个选项直接对应后端枚举，选中即写 localStorage 并重取
通道状态（否则按钮的 disabled 还是按旧角色算的）。

## 错误消息要把修复路径写进去

原来：`本操作需要管理员及以上；当前身份：值班员（请求头 duty）`
现在：`切换气象通道需要「管理员」权限。你当前是「值班员」，可在「设置 → 操作员角色」中切换。`

**把修复路径直接写进错误消息** —— 用户不需要读文档，也不需要猜。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / 'backend-python' / 'traffic' / 'operators.py'
MAIN = ROOT / 'backend-python' / 'main.py'
WORK = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'

# ============================================================
# ① operators：拆成两个 action
# ============================================================
ops = OPS.read_text(encoding='utf-8')
old = """    'weather-mode': 'admin',  # 切气象通道 —— 它会影响这一轮的全部结论"""
new = """    # 0.11.7（F-1）：**拆成两个方向**。
    # 原来进出都要 admin —— 一旦用 admin 切到虚拟态，普通用户在页面上再也切不回来，
    # 这是单向门（复测报告 P0-1 的死锁正是它）。
    # 规则一句话：**往"更不可信"的方向要权限，往"更可信"的方向不要。**
    'weather-mode-to-virtual': 'admin',      # 进虚拟态：会让全场结论变成模拟的
    'weather-mode-to-measured': 'observer',  # 回实测态：任何人，安全侧永远可恢复"""
if old not in ops:
    raise SystemExit('weather-mode action 锚点不存在')
ops = ops.replace(old, new, 1)

old2 = """    return '本操作需要%s及以上；当前身份：%s（请求头 %s）' % (
        need, identity.label, identity.raw or '未提供，按观察员处理')"""
new2 = """    # 0.11.7（F-1）：把**修复路径**写进错误消息。
    # "请求头 duty 是什么"对普通用户是天书 —— 他只知道按钮点不动。
    if action.startswith('weather-mode'):
        hint = '切换气象通道需要「管理员」权限'
        return '%s。你当前是「%s」，可在「设置 → 操作员角色」中切换。' % (hint, identity.label)
    return '本操作需要%s及以上；当前身份：%s（请求头 %s）' % (
        need, identity.label, identity.raw or '未提供，按观察员处理')"""
if old2 not in ops:
    raise SystemExit('deny_message 锚点不存在')
ops = ops.replace(old2, new2, 1)
OPS.write_text(ops, encoding='utf-8')
print('① operators：action 拆两向 + 错误消息带修复路径')

# ============================================================
# ② main.py：按目标模式选 action（顺手修 docstring 位置）
# ============================================================
m = MAIN.read_text(encoding='utf-8')
old3 = """@app.post('/traffic/weather/mode')
def weather_mode_set(req: WeatherModeRequest, request: Request):
    _require(request, 'weather-mode')
    \"\"\"切换气象通道：measured（实测）或 virtual（虚拟）。

    切换在下次请求即生效，无需重启。模式非法时返回 422，不做静默纠正。
    \"\"\""""
new3 = """@app.post('/traffic/weather/mode')
def weather_mode_set(req: WeatherModeRequest, request: Request):
    \"\"\"切换气象通道：measured（实测）或 virtual（虚拟）。

    切换在下次请求即生效，无需重启。模式非法时返回 422，不做静默纠正。

    0.11.7（F-1）：**权限按方向分**。进虚拟态要 admin（它会让全场结论变成模拟的），
    回实测态任何人都可以（安全侧必须永远可恢复）。原来两向都要 admin，
    一旦用 admin 切过去，普通用户在页面上就再也切不回来 —— 单向门。
    \"\"\"
    action = ('weather-mode-to-virtual' if str(req.mode).lower() == 'virtual'
              else 'weather-mode-to-measured')
    _require(request, action)"""
if old3 not in m:
    raise SystemExit('weather_mode_set 锚点不存在')
m = m.replace(old3, new3, 1)
MAIN.write_text(m, encoding='utf-8')
print('② main.py：按方向选 action + docstring 归位')

# ============================================================
# ③ 前端：设置面板加身份切换器
# ============================================================
w = WORK.read_text(encoding='utf-8')

# 3.1 import
old4 = "import {requestJson,postAction} from '../api.js'"
new4 = "import {requestJson,postAction,operatorRole,setOperatorRole} from '../api.js'"
if old4 not in w:
    raise SystemExit('api.js import 锚点不存在')
w = w.replace(old4, new4, 1)

# 3.2 模板：插在「信息密度」label 之后
anchor = '<span class="traffic-session">{{sessionLabel}}'
role_label = ('<label class="settings-density" data-operator-switch><span>操作员角色</span>'
              '<select aria-label="操作员角色" v-model="operator" '
              'title="决定你能做哪些写操作：观察员只读；值班员可暂停/恢复/处置；管理员可切换气象通道" '
              '@change="applyOperator"><option value="observer">观察员（只读）</option>'
              '<option value="duty">值班员（处置）</option>'
              '<option value="admin">管理员（切通道）</option></select></label>')
if 'data-operator-switch' not in w:
    if anchor not in w:
        raise SystemExit('traffic-session 锚点不存在')
    w = w.replace(anchor, role_label + anchor, 1)
    print('③ 模板：操作员角色下拉已加')

# 3.3 script：state + handler
old5 = "async function loadWeatherMode(){"
new5 = """// 0.11.7（F-1）：操作员角色。**这个 ref 是 `setOperatorRole()` 的第一个调用方** ——
// 上一轮我写了那个函数却没有入口，于是 `alc-operator` 永远是默认 duty，
// 而切天气通道要 admin，按钮就焊死在墙上（复测报告 P0-1）。
const operator=ref(operatorRole())
function applyOperator(e){
  const value=e&&e.target?e.target.value:''
  setOperatorRole(value)
  operator.value=operatorRole()
  // 重取通道状态：否则按钮的 disabled 还是按**旧角色**算的，
  // 用户切成管理员了、按钮却仍然是灰的。
  loadWeatherMode()
}

async function loadWeatherMode(){"""
if old5 not in w:
    raise SystemExit('loadWeatherMode 锚点不存在')
w = w.replace(old5, new5, 1)
WORK.write_text(w, encoding='utf-8')
print('④ script：operator ref + applyOperator（重取通道状态）')
