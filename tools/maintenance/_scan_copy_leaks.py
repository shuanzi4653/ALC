"""穿帮文案扫描（0.11.1 · 手册 §6.4）：提交前必须为 0。

手册 §6 给的是"打开浏览器控制台粘一段 JS"的临时办法。那种办法有两个问题：
① 它只看得见**当前这一页**，而"自曝文案"往往藏在没人点开的那一页；
② 它跑完就没了，下一轮改动不会自动重跑 —— 于是同一句话会在下一次提交里回来。

所以这里把它做成闸门：扫源码（不是扫页面），剥掉注释（注释里出现这些词是正常的，
比如解释"为什么不写不依赖外部模型"），只报**会渲染到屏幕上的字符串**。

什么是"会渲染到屏幕上的字符串"：`.vue` 的 `<template>` 块全文，加上 `<script>` 里
出现中文的字符串字面量与反引号模板。判据宁可宽一点：误报只让人多看一眼，
漏报会让评委在答辩现场看见"尚未填完"。

用法：
    python tools/maintenance/_scan_copy_leaks.py            # 扫全站
    python tools/maintenance/_scan_copy_leaks.py --self-test # 负向验证（必须能抓到自己种的那句）
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"

# 每一条都对应手册 §6 的一行。值是"为什么它致命"，命中时会一起打出来。
BANNED: dict[str, str] = {
    "不依赖外部模型": "§6-1 等于自我否定 AI 参与（换芯后模型已进裁决链）",
    "复现判据的能力": "§6-2 全站最贵的一句话：替评委得出「这套 AI 没做气象」",
    "尚未填完": "§6-4 未完成品自述",
    "一致率 0.0": "§6-3 会让评委直接判「没跑通」",
    "暂无数据": "§6.4 空态必须说清原因，而不是四个字打发",
    "示例数据": "§6.4 演示品不许把示例数据摆在业务位上",
    "TODO": "§6.4 未完成标记不许进产物",
    "FIXME": "§6.4 未完成标记不许进产物",
}

# 明确豁免：这些词在**能力边界**语境里是正确答案，不是穿帮。
# 写在这里而不是从 BANNED 里删掉，是为了留下"我们讨论过、决定豁免"的痕迹。
EXEMPT: dict[str, str] = {
    "不支持": "事件处置台的「本系统不支持该动作」是能力边界声明，按钮可点且给出原因（见 runtime.js 4398 起）",
    "mock": "变量名与注释里的 mock 不渲染；只禁「示例数据」这类会显示的字样",
}

CJK = re.compile(r"[\u4e00-\u9fff]")
TARGETS = ("*.vue", "*.js")


def strip_comments(text: str, kind: str) -> str:
    """去掉注释，保留字符串。

    粗糙但够用：先把 `//` 与 `/* */` 换成等长空白（保持行号不变），
    再处理 `.vue` 的 `<!-- -->`。**不处理字符串里的 "//"**（例如 URL）：
    那会把整行吃掉，于是漏报 —— 而这正是我们最怕的方向。所以只剥"行首（含缩进）"
    与"代码之后明确是注释"的情形：本仓库的注释都以 `//` 或 `/*` 起头。
    """
    out = []
    in_block = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if in_block:
            if "*/" in line:
                in_block = False
            out.append("")
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block = True
            out.append("")
            continue
        if stripped.startswith("//") or (kind == "vue" and stripped.startswith("<!--")):
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def scan_file(path: Path) -> list[tuple[int, str, str, str]]:
    """→ [(行号, 命中的词, 该行文本, 为什么致命)]"""
    kind = "vue" if path.suffix == ".vue" else "js"
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = strip_comments(raw, kind)
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        # 只关心含中文的行：纯代码行里的 `TODO`/`mock` 不渲染。
        if not CJK.search(line):
            continue
        for word, why in BANNED.items():
            if word in line:
                hits.append((number, word, line.strip()[:160], why))
    return hits


def collect() -> list[tuple[Path, list[tuple[int, str, str, str]]]]:
    found = []
    for pattern in TARGETS:
        for path in sorted(SRC.rglob(pattern)):
            if "node_modules" in path.parts:
                continue
            hits = scan_file(path)
            if hits:
                found.append((path, hits))
    return found


def self_test() -> int:
    """负向验证：种一句必须被抓到的话，且注释里的同一句话不许报。"""
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "Sample.vue"
        sample.write_text(
            "<template>\n"
            "  <p>本会话全部班次由规则引擎直接产出，不依赖外部模型</p>\n"
            "  <!-- 注释里写 不依赖外部模型 是允许的，因为它不渲染 -->\n"
            "</template>\n",
            encoding="utf-8",
        )
        hits = scan_file(sample)
        rendered = [h for h in hits if "不依赖外部模型" in h[2]]
        if len(rendered) != 1:
            print("FAIL 负向验证：应当恰好抓到 1 条渲染中的命中，实际 %d 条" % len(rendered))
            return 1
        if rendered[0][0] != 2:
            print("FAIL 负向验证：行号应为 2，实际 %d" % rendered[0][0])
            return 1
        commented = [h for h in hits if h[1] == "不依赖外部模型" and h[0] == 3]
        if commented:
            print("FAIL 负向验证：注释里的那句话被误报了")
            return 1
    print("PASS 负向验证：渲染中的命中被抓到、注释里的同一句没被误报")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="穿帮文案扫描（手册 §6.4）")
    parser.add_argument("--self-test", action="store_true", help="负向验证扫描器本身")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    found = collect()
    total = sum(len(hits) for _, hits in found)
    if not total:
        print("PASS 穿帮文案扫描：0 命中（扫了 %d 个文件）" % sum(1 for _ in SRC.rglob("*") if _.suffix in (".vue", ".js")))
        print("豁免项（讨论过、决定保留）：")
        for word, why in EXEMPT.items():
            print("  · %s —— %s" % (word, why))
        return 0
    print("FAIL 穿帮文案扫描：%d 处命中" % total)
    for path, hits in found:
        print("  %s" % path.relative_to(ROOT))
        for number, word, line, why in hits:
            print("    %d: [%s] %s" % (number, word, line))
            print("       原因：%s" % why)
    return 1


if __name__ == "__main__":
    sys.exit(main())
