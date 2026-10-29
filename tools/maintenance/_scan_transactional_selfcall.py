"""扫 Java 侧「@Transactional 被同类自调用」的隐形失效。

判据：`@Transactional` 只对**经 Spring 代理**的调用生效。若 A 方法（带注解）只在
同类的另一个方法里被裸调用（`a()`，而不是 `self.a()` / `other.a()`），代理被绕过、
注解等于注释。

本脚本做文本级判定，输出三档：
  BROKEN   —— 带注解的方法，只在本类内被裸调用（确定失效）
  SUSPECT  —— 带注解且在类内被裸调用，但外部也可能调用（需人工看是否只走内部）
  OK       —— 没有类内裸调用

用法：python tools/maintenance/_scan_transactional_selfcall.py
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / 'backend-java' / 'src' / 'main' / 'java'

# 方法签名：public/private/protected [修饰] 返回类型 名字(
SIG = re.compile(
    r'^\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?'
    r'[\w<>\[\],.\s?]+?\s+(\w+)\s*\(', re.M)


def analyse(path: pathlib.Path) -> list[dict]:
    src = path.read_text(encoding='utf-8')
    lines = src.split('\n')

    # 1) 找出所有 @Transactional 标注的方法名
    annotated: list[tuple[str, int]] = []
    for i, line in enumerate(lines):
        if '@Transactional' in line and not line.strip().startswith('*'):
            # 往下找最近的方法签名（跳过其他注解与空行）
            for j in range(i + 1, min(i + 8, len(lines))):
                m = SIG.match(lines[j])
                if m:
                    annotated.append((m.group(1), j + 1))
                    break
    if not annotated:
        return []

    # 2) 全类方法名集合（用于区分「调用」与「定义」）
    all_methods = {m.group(1) for m in SIG.finditer(src)}

    results = []
    for name, decl_line in annotated:
        bare = 0
        proxied = 0
        call_sites = []
        for i, line in enumerate(lines, start=1):
            if i == decl_line:
                continue
            if line.strip().startswith('*') or line.strip().startswith('//'):
                continue
            for m in re.finditer(rf'(?<![\w.])(\w+)\s*\.\s*{re.escape(name)}\s*\(', line):
                proxied += 1
                call_sites.append((i, 'proxied', m.group(1)))
            for m in re.finditer(rf'(?<![\w.]){re.escape(name)}\s*\(', line):
                # 排除定义行本身、排除方法声明
                bare += 1
                call_sites.append((i, 'bare', ''))
        results.append({
            'method': name, 'decl_line': decl_line,
            'bare': bare, 'proxied': proxied, 'sites': call_sites,
        })
    return results


def main() -> int:
    broken = suspect = ok = 0
    for path in sorted(SRC.rglob('*.java')):
        rows = analyse(path)
        if not rows:
            continue
        rel = path.relative_to(ROOT)
        for r in rows:
            if r['bare'] == 0:
                ok += 1
                continue
            # 有裸调用 → 看是不是还有代理调用
            if r['proxied'] > 0:
                tag, suspect = 'SUSPECT', suspect + 1
            else:
                tag, broken = 'BROKEN ', broken + 1
            print(f'{tag} {rel}:{r["decl_line"]}  {r["method"]}()  '
                  f'裸调用 {r["bare"]} 次 / 代理调用 {r["proxied"]} 次')
            for line_no, kind, via in r['sites'][:4]:
                print(f'         L{line_no}  {kind}' + (f'（经 {via}）' if via else ''))
    print()
    print(f'汇总：BROKEN {broken} · SUSPECT {suspect} · OK {ok}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
