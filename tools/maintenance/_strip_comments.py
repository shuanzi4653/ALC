"""把源码里"长篇解释型注释"归档到本地 md，并从代码里删掉。

背景
----
项目里积累了大量 `# 为什么这样做` 式的多行注释与 docstring。它们的价值在
`docs/`、`changelog/ISSUES.md` 与 `.workbuddy/memory/notes/` 里已经有了副本；
留在代码里的那部分只做两件事：让文件变长、让交付物看起来不像一支团队长期维护的代码。

所以：**长块删掉、短句留下**。判据是机械的，不看内容：

  · 连续注释块 ≥ 2 行，或单块 ≥ 100 字  → 删，归档
  · 行尾注释 ≥ 60 字                    → 删，归档
  · 多行 docstring（Python）            → 删，归档
  · 单行注释 / 单行 docstring            → 留（正常代码本来就有）

功能性注释**永不删**：`# noqa`、`# type:`、`# pragma`、`#!`、`# -*- coding`、
`// @ts-`、`/* eslint`、`<!-- prettier`。删掉它们会改变行为（lint/类型检查/构建）。

不碰的三类文件（各有硬理由）
--------------------------
1. `db/migration/*.sql` —— **Flyway 会对迁移文件算校验和**。改一个字符，线上库里
   已应用的版本就会 `checksum mismatch`，应用直接起不来。注释再长也不能动。
2. `*.min.js` / `dist/` —— 构建产物，注释在打包时已被去掉，不需要也不应该手改。
3. 测试文件（`tests/`、`*Test.java`）—— 它们不随产物发布，且注释里常写着判据的来源。

用法
----
    python tools/maintenance/_strip_comments.py --dry-run
    python tools/maintenance/_strip_comments.py --archive docs/代码注释归档-V1.0.0.md
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = [
    ('py', ROOT / 'backend-python', {'.py'}),
    ('java', ROOT / 'backend-java' / 'src' / 'main' / 'java', {'.java'}),
    ('web', ROOT / 'frontend' / 'src', {'.js', '.vue'}),
]
SKIP_DIRS = {'.venv', 'node_modules', 'dist', '__pycache__', 'tests', 'test', 'experiments'}
SKIP_FILES = {'application.yml'}          # 配置注释保留：它是给运维看的说明，不是"解释代码"
KEEP_MARKERS = ('# noqa', '# type:', '# pragma', '#!', '# -*-', '// @ts-', '/* eslint',
                '<!--', 'eslint-disable', 'prettier-ignore')

MIN_BLOCK_LINES = 2
MIN_BLOCK_CHARS = 100
MIN_TRAILING_CHARS = 60


def keepable(text: str) -> bool:
    low = text.strip().lower()
    return any(marker in low for marker in KEEP_MARKERS)


def too_long(lines: list[str], trailing: bool) -> bool:
    """删不删。**默认删**，只留功能性标记与短的单行 docstring。

    第一版是"只删长块"（≥2 行 / ≥100 字），实测留下的是残句：一行行尾注释被保留，
    它下面那行"续写"的整行注释却被判成长块删掉，代码里就出现半句话 ——
    比原来更难看。既然目标是把解释搬进文档，就别做一半。
    """
    body = ' '.join(lines).strip()
    if keepable(body):
        return False
    return True


def keep_docstring(text: str, span: int) -> bool:
    stripped = text.strip()
    return span == 1 and len(stripped) <= 40 and '\n' not in stripped


# --------------------------------------------------------------------------- python
def strip_python(path: Path, archive: list) -> str:
    source = path.read_text(encoding='utf-8')
    lines = source.split('\n')
    drop: set[int] = set()          # 0-based 行号
    cuts: dict[int, int] = {}       # 行号 -> 从第几列截断（行尾注释）

    with io.BytesIO(source.encode('utf-8')) as buf:
        tokens = list(tokenize.tokenize(buf.readline))
    block: list[tuple[int, str]] = []

    def flush():
        nonlocal block
        if not block:
            return
        texts = [t for _, t in block]
        if too_long(texts, trailing=False):
            archive.append((path, block[0][0], '\n'.join(texts)))
            for ln, _ in block:
                drop.add(ln - 1)
        block = []

    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            full_line = lines[row - 1]
            if not full_line[:col].strip():          # 整行注释
                block.append((row, full_line.strip()))
                continue
            flush()
            if too_long([tok.string], trailing=True):
                archive.append((path, row, tok.string))
                cuts[row - 1] = col
        elif tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            continue
        else:
            flush()
    flush()

    # docstring：多行的整段删；单行的按长短决定
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, 'body', None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        start, end = first.lineno, first.end_lineno
        text = first.value.value
        span = end - start + 1
        if not keep_docstring(text, span):
            if keepable(text):
                continue
            archive.append((path, start, text))
            if len(body) == 1:
                # 块体只有这一句 docstring：删掉会让 `def f():` / `class A:` 后面空着
                # （IndentationError）⇒ 留一个 `pass`。
                indent = ' ' * first.col_offset
                lines[start - 1] = indent + 'pass'
                for ln in range(start + 1, end + 1):
                    drop.add(ln - 1)
                continue
            for ln in range(start, end + 1):
                drop.add(ln - 1)

    out = []
    for idx, line in enumerate(lines):
        if idx in drop:
            continue
        if idx in cuts:
            line = line[:cuts[idx]].rstrip()
        out.append(line)
    return '\n'.join(out)


# --------------------------------------------------------------------------- brace languages
def scan_c_like(text: str, line_comment: str = '//', block_open: str = '/*',
                block_close: str = '*/') -> list[tuple[int, int, str, bool]]:
    """返回 [(start, end, body, is_full_line)]；字符串/模板/正则里的符号不算注释。"""
    spans = []
    i, n = 0, len(text)
    line_start = 0
    while i < n:
        ch = text[i]
        if ch == '\n':
            line_start = i + 1
            i += 1
        elif ch in '"\'':
            quote = ch
            i += 1
            while i < n:
                if text[i] == '\\':
                    i += 2
                    continue
                if text[i] == quote or text[i] == '\n':
                    i += 1
                    break
                i += 1
        elif ch == '`':
            i += 1
            depth = 0
            while i < n:
                if text[i] == '\\':
                    i += 2
                    continue
                if text[i] == '$' and i + 1 < n and text[i + 1] == '{':
                    depth += 1
                    i += 2
                    continue
                if text[i] == '}' and depth:
                    depth -= 1
                    i += 1
                    continue
                if text[i] == '`' and depth == 0:
                    i += 1
                    break
                i += 1
        elif text.startswith(block_open, i):
            end = text.find(block_close, i + 2)
            end = n if end < 0 else end + 2
            body = text[i:end]
            full = not text[line_start:i].strip()
            spans.append((i, end, body, full))
            i = end
        elif text.startswith(line_comment, i):
            # 行首的 `//` 后面紧跟 `/` 时是 URL/协议写法（`http://`），不是注释
            if line_comment == '//' and i > 0 and text[i - 1] == ':':
                i += 2
                continue
            end = text.find('\n', i)
            end = n if end < 0 else end
            body = text[i:end]
            full = not text[line_start:i].strip()
            spans.append((i, end, body, full))
            i = end
        else:
            i += 1
    return spans


def _line_start_if_blank(text: str, pos: int) -> int:
    """若 pos 之前只剩缩进，返回行首；否则原样返回。"""
    line_start = text.rfind('\n', 0, pos) + 1
    return line_start if not text[line_start:pos].strip() else pos


def strip_c_like(path: Path, archive: list) -> str:
    text = path.read_text(encoding='utf-8')
    spans = scan_c_like(text)
    grouped: list[tuple[int, int, str]] = []
    i = 0
    while i < len(spans):
        start, end, body, full = spans[i]
        if not full:
            if too_long([body], trailing=True):
                archive.append((path, text.count('\n', 0, start) + 1, body))
                grouped.append((start, end, ''))
            i += 1
            continue
        # 连续整行注释合并成一块（块注释与行注释可以相邻）
        j = i
        chunk = [body]
        last_end = end
        while j + 1 < len(spans):
            nxt_start, nxt_end, nxt_body, nxt_full = spans[j + 1]
            between = text[last_end:nxt_start]
            if not nxt_full or between.strip():
                break
            chunk.append(nxt_body)
            last_end = nxt_end
            j += 1
        while chunk and chunk[-1].strip() == '':
            chunk.pop()
        if chunk and too_long(chunk, trailing=False):
            line_no = text.count('\n', 0, start) + 1
            archive.append((path, line_no, '\n'.join(chunk)))
            # 连同行尾换行一起去掉，避免留下空行堆
            cut_end = last_end
            while cut_end < len(text) and text[cut_end] in ' \t':
                cut_end += 1
            if cut_end < len(text) and text[cut_end] == '\n':
                cut_end += 1
            start = _line_start_if_blank(text, start)
            grouped.append((start, cut_end, ''))
        i = j + 1

    for start, end, repl in reversed(grouped):
        text = text[:start] + repl + text[end:]
    return text


def strip_vue(path: Path, archive: list) -> str:
    text = path.read_text(encoding='utf-8')
    # 模板里的 <!-- --> 与样式里的 /* */，按块切开分别处理
    out = text
    for tag in ('template', 'style'):
        m = re.search(r'<%s[^>]*>' % tag, out)
        if not m:
            continue
        close = out.rfind('</%s>' % tag)
        if close < m.end():
            continue
        if close < 0:
            continue
        inner = out[m.end():close]
        if tag == 'template':
            spans = [(s, e, inner[s:e], True) for s, e, body, full in
                     _html_comments(inner)]
        else:
            spans = scan_c_like(inner, block_open='/*', block_close='*/')
        grouped = []
        for start, end, body, full in spans:
            body_lines = body.split('\n')
            if too_long(body_lines, trailing=not full):
                archive.append((path, out.count('\n', 0, m.end() + start) + 1, body))
                cut_end = end
                while cut_end < len(inner) and inner[cut_end] in ' \t':
                    cut_end += 1
                if cut_end < len(inner) and inner[cut_end] == '\n':
                    cut_end += 1
                grouped.append((_line_start_if_blank(inner, start), cut_end))
        for start, end in reversed(grouped):
            inner = inner[:start] + inner[end:]
        out = out[:m.end()] + inner + out[close:]
    # 兜底：不在上面那段范围里的 <!-- -->（块外、嵌套层）一并删掉
    while True:
        mm = re.search(r'<!--[\s\S]*?-->', out)
        if not mm:
            break
        archive.append((path, out.count('\n', 0, mm.start()) + 1, mm.group(0)))
        start = _line_start_if_blank(out, mm.start())
        end = mm.end()
        while end < len(out) and out[end] in ' \t':
            end += 1
        if end < len(out) and out[end] == '\n':
            end += 1
        out = out[:start] + out[end:]

    # script 块交给 JS 扫描器（整份文件里只有 script 会用到 // 与 /* */）
    m = re.search(r'<script[^>]*>', out)
    if m:
        close = out.find('</script>', m.end())
        if close > 0:
            inner = out[m.end():close]
            spans = scan_c_like(inner)
            grouped = []
            idx = 0
            while idx < len(spans):
                start, end, body, full = spans[idx]
                if not full:
                    if too_long([body], trailing=True):
                        archive.append((path, out.count('\n', 0, m.end() + start) + 1, body))
                        grouped.append((start, end))
                    idx += 1
                    continue
                j = idx
                chunk = [body]
                last_end = end
                while j + 1 < len(spans):
                    ns, ne, nb, nf = spans[j + 1]
                    if not nf or inner[last_end:ns].strip():
                        break
                    chunk.append(nb)
                    last_end = ne
                    j += 1
                if chunk and too_long(chunk, trailing=False):
                    archive.append((path, out.count('\n', 0, m.end() + start) + 1, '\n'.join(chunk)))
                    cut_end = last_end
                    while cut_end < len(inner) and inner[cut_end] in ' \t':
                        cut_end += 1
                    if cut_end < len(inner) and inner[cut_end] == '\n':
                        cut_end += 1
                    grouped.append((_line_start_if_blank(inner, start), cut_end))
                idx = j + 1
            for start, end in reversed(grouped):
                inner = inner[:start] + inner[end:]
            out = out[:m.end()] + inner + out[close:]
    return out


def _html_comments(text: str):
    out = []
    i = 0
    while True:
        start = text.find('<!--', i)
        if start < 0:
            break
        end = text.find('-->', start + 4)
        if end < 0:
            break
        out.append((start, end + 3, text[start:end + 3], True))
        i = end + 3
    return out


def tidy(text: str) -> str:
    """收拾删除留下的痕迹：行首空行、行尾空格、三行以上的空行。"""
    text = text.lstrip('\n')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    if not text.endswith('\n'):
        text += '\n'
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--archive', default='docs/代码注释归档-V1.0.0.md')
    ap.add_argument('--only', default='', help='py / java / web')
    ap.add_argument('--files', default='', help='逗号分隔的文件名片段，只处理命中的文件')
    args = ap.parse_args()

    archive: list = []
    per_kind: dict[str, int] = {}
    changed = 0
    total_before = 0
    total_after = 0
    for kind, base, exts in TARGETS:
        if args.only and kind != args.only:
            continue
        if not base.exists():
            continue
        for path in sorted(base.rglob('*')):
            if path.suffix not in exts or not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.name in SKIP_FILES:
                continue
            if args.files and not any(frag in path.as_posix() for frag in args.files.split(',')):
                continue
            before = path.read_text(encoding='utf-8')
            try:
                if kind == 'py':
                    after = strip_python(path, archive)
                elif kind == 'java':
                    after = strip_c_like(path, archive)
                else:
                    after = strip_vue(path, archive) if path.suffix == '.vue' else strip_c_like(path, archive)
            except SyntaxError as error:
                print('SKIP %s: %s' % (path.relative_to(ROOT), error))
                continue
            after = tidy(after)
            if after != before:
                changed += 1
                per_kind[kind] = per_kind.get(kind, 0) + 1
                total_before += len(before.split('\n'))
                total_after += len(after.split('\n'))
                if not args.dry_run:
                    path.write_text(after, encoding='utf-8', newline='')
    for kind, n in per_kind.items():
        print('  %-5s files=%d' % (kind, n))
    print('files changed %d | lines %d -> %d (-%d) | archived blocks %d'
          % (changed, total_before, total_after, total_before - total_after, len(archive)))
    if args.dry_run:
        print('（--dry-run，未写盘）')
        return 0

    target = ROOT / args.archive
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8', newline='') as fh:
        fh.write('# 代码注释归档（迁移自源码，V1.0.0）\n\n')
        fh.write('> 源码里那些"为什么这样做"的长注释已从代码中移到这里，按文件与起始行归档。\n')
        fh.write('> 判据与取舍见 `tools/maintenance/_strip_comments.py`。\n\n')
        current = None
        for path, line, body in archive:
            rel = path.relative_to(ROOT).as_posix()
            if rel != current:
                fh.write('\n## %s\n\n' % rel)
                current = rel
            fh.write('### L%d\n\n```\n%s\n```\n\n' % (line, body.strip()))
    print('archive ->', target.relative_to(ROOT), '%.1f KB' % (target.stat().st_size / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
