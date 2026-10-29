"""闸门失败回报路径的自证（0.9.26（Beta） 第十轮）。

为什么需要这个探针
------------------
`tools/maintenance/_gate_toolchain.py` 在**成功**时只打印每个审计的一行 `ok`，
而把"到底哪里坏了"的说明放在**失败路径**里。那段代码在 0.9.26（Beta） 第十轮
之前**一次都没有被执行过** —— 直到 `gateway routes` 审计第一次真的失败：

    TypeError: not all arguments converted during string formatting

原因是 `reason` 是一个**二元组** `(标题, 第一行证据)`，而失败路径写的是
`print("  %s" % reason)`；`"%s" % (a, b)` 必然抛 `TypeError`。于是症状是：

  **任何一条审计真的失败时，闸门不是打印原因，而是崩在打印原因的代码里。**

这条缺陷的恶劣之处在于它的可见性：构建、测试、"闸门跑通了"全都不会变红。
它只在需要它的那一刻失效，而那一刻本来就少见（M27：量具必须自证）。

本探针怎么证明修好了
--------------------
1. 直接调用抽出来的 `_report()`，喂进**两种形状**的失败（元组 / 字符串）
   —— 两种都要打印出标题，元组还要打印证据行；
2. 断言空列表走 `GATE PASS` 且返回 0；
3. **负向对照**：复现旧写法 `"%s" % (a, b)`，断言它**确实**抛 `TypeError`。
   没有这一步，"改了格式化"与"这个 bug 根本不存在"在输出上无法区分。

退出码：0 通过 / 1 量出来是坏的 / 2 无法测量（M60）。

跑法：
  python tools/probes/_probe_gate_report.py
"""
import importlib.util
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
GATE = os.path.join(ROOT, "tools", "maintenance", "_gate_toolchain.py")


def _load_gate():
    """按路径加载闸门模块。

    不用 `import _gate_toolchain`：那个模块不在 `sys.path` 上，而为了导入它去改
    `sys.path` 会顺带把 `tools/maintenance` 变成可导入命名空间 —— 那正是
    `_check_unbound_names.py` / `_audit_payload_imports.py` 在防的事情。
    按路径加载只影响本进程，不改变任何全局查找规则。
    """
    spec = importlib.util.spec_from_file_location("_alc_gate_toolchain", GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载闸门模块：%s" % GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if not os.path.isfile(GATE):
        print("[EXIT 2] 无法测量：找不到 %s" % GATE)
        return 2
    try:
        gate = _load_gate()
    except Exception as exc:                                    # pragma: no cover
        print("[EXIT 2] 无法测量：加载闸门失败 —— %s" % exc)
        return 2
    if not hasattr(gate, "_report"):
        print("[EXIT 2] 无法测量：闸门没有 `_report()` —— 失败回报不再是一个可调用的单元，")
        print("          本探针测不到它。这本身要当作失败处理，而不是当作通过。")
        return 2

    ok = True

    # ---- 1. 空列表：成功路径 ----
    buffer = io.StringIO()
    code = gate._report([], stream=buffer)
    text = buffer.getvalue()
    if code == 0 and "GATE PASS" in text:
        print("[PASS] 空失败列表走 GATE PASS 且返回 0")
    else:
        print("[FAIL] 空失败列表没有走成功路径（返回 %s）：%r" % (code, text))
        ok = False

    # ---- 2. 元组形状：这是真实审计的形状 ----
    tuple_failure = [("gateway routes", ("unrouted frontend calls", "  DEAD  /api/traffic/journal"), "raw output")]
    buffer = io.StringIO()
    code = gate._report(tuple_failure, stream=buffer)
    text = buffer.getvalue()
    for fragment in ("GATE FAIL -- 1", "=== gateway routes ===", "  unrouted frontend calls",
                     "  |   DEAD  /api/traffic/journal"):
        if fragment not in text:
            print("[FAIL] 元组形状的失败漏印了一段：%r" % fragment)
            ok = False
    if code != 1:
        print("[FAIL] 有失败却返回 %s（应为 1）" % code)
        ok = False
    if ok:
        print("[PASS] 元组形状的失败印出标题与证据行，且返回 1")

    # ---- 3. 字符串形状：伴随闸门（`_companion_gates`）用的是这一种 ----
    buffer = io.StringIO()
    code = gate._report([("behavioural gate", "exited 2", "raw output")], stream=buffer)
    text = buffer.getvalue()
    if "=== behavioural gate ===" in text and "  exited 2" in text and "\n  | " not in text:
        print("[PASS] 字符串形状的失败印出标题，且不硬凑一行证据")
    else:
        print("[FAIL] 字符串形状的失败打印不对：%r" % text)
        ok = False

    # ---- 4. 负向对照：旧写法必须真的会炸 ----
    #
    # 这一条是整个探针的牙齿。它复现**旧实现的表达式**（不是旧代码 —— 旧代码已被
    # 替换），证明那个 `TypeError` 是真的会发生，而不是我事后推断出来的。
    # 少了它，"我把 `%%s` 拆开了"与"这里本来就没问题"读起来一模一样。
    raised = None
    try:
        _ = "%s" % ("unrouted frontend calls", "  DEAD  /api/traffic/journal")
    except TypeError as exc:
        raised = str(exc)
    if raised is None:
        print("[FAIL] 负向对照没有牙齿：旧写法 `\"%s\" % (a, b)` 竟然没有抛异常")
        ok = False
    else:
        print("[PASS] 负向对照有效：旧写法确实抛 TypeError（%s）" % raised)

    # ---- 5. 回归守卫：失败路径必须**还**走 `_report` ----
    #
    # 上一条证明了"改对了"，这一条防的是"又改回去"。少了它，下一个人把打印重新
    # 内联进 `main()` 时，探针仍然全绿 —— 因为它调的是那个**已经没人调用**的函数。
    # 判据必须落在"谁在调用它"上，而不是"它自己还对不对"。
    #
    # **为什么不再额外搜一次旧写法的字面量**：那样做会命中 `_report` 自己的说明文字
    # （里面引用了这行代码），是纯粹的假阳性；而且它在逻辑上是**冗余**的 ——
    # 旧写法若被写回 `_report` 内部，上面第 2 步会直接抛异常（探针以非 0 退出）；
    # 若被写回 `main()`，本条判据就会因为 `return _report(failed)` 消失而触发。
    # 一个只在假阳性时才报警的判据，比没有这条判据更坏。
    source = open(GATE, encoding="utf-8").read()
    if "return _report(failed)" not in source:
        print("[FAIL] `main()` 不再调用 `_report()` —— 探针测的是一个死函数")
        ok = False
    else:
        print("[PASS] 回归守卫：失败路径仍由 `main()` 调用 `_report()`")

    print()
    print("GATE REPORT " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
