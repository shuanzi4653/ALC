"""闸门：前端未绑定名 / 越界 `<script>` 块（0.11.8）。

**为什么需要这一条**：`_audit_unbound_names.py` 是 Python AST，`vite build` 只解析
语法，Vue 模板里的未知名字会退化成 `_ctx.x`（渲染成空、不抛错）。于是"JS 里写了一个
本文件不存在的名字"这一类错，**整个工具链没有一张网**（M23 记的就是这件事）。

2026-10-21 线上两次撞上它：
  ① `TrafficWorkbench` 用 `activeCaseId`（该变量在另一个组件里）→ **实时首页气象层
     整块加载失败**，横幅写"本帧已作废"，看着像后端坏了；
  ② `CityTrafficMap` 的三个雾区函数被补丁追加到 `</script>` **之后** → 每次重画抛
     ReferenceError，连 `map.triggerRepaint()` 都跳过。
两次都是 **构建绿、435 条测试绿、闸门 27 项绿**。

三出口（与项目其他量具一致）：
  0 干净 / 1 有发现 / 2 无法测量（找不到 node、@babel/parser、解析失败）
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / 'tools' / 'maintenance' / 'js_unbound_scan.mjs'

sys.path.insert(0, str(ROOT / 'tools'))
from shared import _node  # noqa: E402


def run(targets):
    proc = subprocess.run(
        [_node.NODE, str(SCANNER), *targets],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
        encoding='utf-8', errors='replace')
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


CLEAN_JS = """\
import { computed, ref } from 'vue'

const props = defineProps({ rows: { type: Array, default: () => [] } })
const count = ref(0)

// 注释里出现一个不存在的名字 activeCaseId 不算 —— 这是**注释不是代码**
export function total() {
  const doubled = computed(() => props.rows.map(row => row.value * 2))
  const label = `${count.value} 条`
  return { doubled: doubled.value.length, label, ok: globalThis?.crypto != null }
}
"""

UNBOUND_JS = """\
export function fetchWeather(seed) {
  // 与线上那次同形：名字来自另一个文件，本文件没有声明
  return `/api/traffic/weather?seed=${seed}${activeCaseId ? `&case=${activeCaseId}` : ''}`
}
"""

CLEAN_VUE = """\
<script setup>
const stationVisibility = []
function paintFogCircles() { return stationVisibility.length }
paintFogCircles()
</script>

<template><div>{{ stationVisibility.length }}</div></template>
"""

STRAY_VUE = """\
<script setup>
function paintFogCircles() { return 1 }
</script>

// ---- 这一段本来该在 </script> 里面 ----
function fogRing() { return 1 }

<template><div/></template>
"""


def self_test():
    """四条负向样本。一条不会红的判据等于没有判据。"""
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / 'clean.js').write_text(CLEAN_JS, encoding='utf-8')
        (tmp_dir / 'unbound.js').write_text(UNBOUND_JS, encoding='utf-8')
        (tmp_dir / 'clean.vue').write_text(CLEAN_VUE, encoding='utf-8')
        (tmp_dir / 'stray.vue').write_text(STRAY_VUE, encoding='utf-8')

        def case(name, files, expect_rc, expect_text):
            nonlocal failures
            code, out = run([str(tmp_dir / f) for f in files])
            ok = code == expect_rc and (expect_text in out if expect_text else True)
            if ok:
                print('PASS 负向 %s' % name)
            else:
                failures += 1
                print('FAIL 负向 %s：rc=%s（期望 %s）\n%s' % (name, code, expect_rc, out.strip()[:400]))

        # ① 正常样本必须过（防误报：注释、模板字符串、属性名、可选链、宏）
        case('正常 .js 通过', ['clean.js'], 0, 'unbound names: 0')
        # ② 未绑定名必须被抓（就是这次线上那个形状）
        case('未绑定名被抓', ['unbound.js'], 1, 'activeCaseId')
        # ③ 正常 .vue 必须过（`<script setup>` 里的顶层函数互相可见）
        case('正常 .vue 通过', ['clean.vue'], 0, 'unbound names: 0')
        # ④ `</script>` 之后的代码必须被抓
        case('越界块被抓', ['stray.vue'], 1, 'stray')

    print('self-test %s' % ('PASSED' if failures == 0 else 'FAILED'))
    return 1 if failures else 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    if not SCANNER.exists():
        print('SKIP no %s —— 无法测量' % SCANNER)
        return 2
    code, out = run([str(ROOT / 'frontend' / 'src')])
    print(out.strip())
    if code == 0:
        print('ok   frontend has no unbound names and no stray <script> blocks')
        return 0
    if code == 2:
        print('SKIP scanner could not measure (see above)')
        return 2
    return 1


if __name__ == '__main__':
    sys.exit(main())
