# -*- coding: utf-8 -*-
"""把 05-作品方案-正文 的 Markdown 子集渲染成 DOCX（供 Word 导出 PDF）。

只支持本文用到的那几个语法：标题、段落、列表、表格、引用、代码块、行内 **粗体** / `代码`。
这样做的好处是排版参数（字号、行距、表格边框）全部在这里集中控制，改版式不用碰正文。
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'docs' / '国赛-11-13' / '05-作品方案-正文-20261112.md'
OUT_DIR = ROOT / 'docs' / '国赛-11-13' / '提交'
OUT = OUT_DIR / 'AIC-2026-41989115-智慧气象-天窗智巡-作品方案.docx'

BODY_FONT = '宋体'
HEAD_FONT = '黑体'
MONO_FONT = 'Consolas'
INK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x55, 0x55, 0x55)


def set_run_font(run, name=BODY_FONT, size=None, bold=None, color=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn('w:eastAsia'), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def add_page_number_footer(section):
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('— ')
    set_run_font(run, BODY_FONT, 9, color=GREY)
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), 'PAGE')
    r = OxmlElement('w:r')
    rpr = OxmlElement('w:rPr')
    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), '18')
    rpr.append(sz)
    r.append(rpr)
    t = OxmlElement('w:t')
    t.text = '1'
    r.append(t)
    fld.append(r)
    p._p.append(fld)
    run2 = p.add_run(' —')
    set_run_font(run2, BODY_FONT, 9, color=GREY)


def shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def set_cell_margins(table, left=80, right=80, top=40, bottom=40):
    tblPr = table._tbl.tblPr
    mar = OxmlElement('w:tblCellMar')
    for tag, val in (('left', left), ('right', right), ('top', top), ('bottom', bottom)):
        el = OxmlElement(f'w:{tag}')
        el.set(qn('w:w'), str(val))
        el.set(qn('w:type'), 'dxa')
        mar.append(el)
    tblPr.append(mar)


def table_borders(table):
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), '4')
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), 'BFBFBF')
        borders.append(el)
    tblPr.append(borders)


INLINE = re.compile(r'(\*\*.+?\*\*|`[^`]+`)')


def add_inline(par, text, size=10.5, bold=False, color=INK, font=BODY_FONT):
    for piece in INLINE.split(text):
        if not piece:
            continue
        if piece.startswith('**') and piece.endswith('**'):
            run = par.add_run(piece[2:-2])
            set_run_font(run, font, size, True, color)
        elif piece.startswith('`') and piece.endswith('`'):
            run = par.add_run(piece[1:-1])
            set_run_font(run, MONO_FONT, size - 0.5, bold, color)
        else:
            run = par.add_run(piece)
            set_run_font(run, font, size, bold, color)


def build_cover(doc, lines):
    for _ in range(3):
        doc.add_paragraph()
    for idx, line in enumerate(lines):
        text = line.strip()
        if not text:
            continue
        if text.startswith('# '):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(18)
            add_inline(p, text[2:], size=26, bold=True, font=HEAD_FONT)
        elif text.startswith('## '):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(40)
            add_inline(p, text[3:], size=15, bold=False, color=GREY, font=HEAD_FONT)
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6)
            add_inline(p, text, size=12)
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)


def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement('w:tblHeader')
    el.set(qn('w:val'), 'true')
    trPr.append(el)


def emit_table(doc, rows):
    header, body = rows[0], rows[1:]
    table = doc.add_table(rows=len(rows), cols=len(header))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # 固定列宽：自动布局遇到长中文单元格会把表格顶出右边距，宁可窄一点也要保证不越界
    table.autofit = False
    table_borders(table)
    set_cell_margins(table)
    total = 16.0  # 21 - 2.6 - 2.4 cm
    weights = []
    for j in range(len(header)):
        lens = [len(r[j]) for r in rows if j < len(r)]
        weights.append(max(4, min(60, (sum(lens) / max(1, len(lens))) ** 0.6)))
    ssum = sum(weights) or 1
    widths = [max(2.2, total * w / ssum) for w in weights]
    scale = total / sum(widths)
    widths = [w * scale for w in widths]
    for j, w in enumerate(widths):
        for row in table.columns[j].cells:
            row.width = Cm(w)
    repeat_header(table.rows[0])
    for j, cell_text in enumerate(header):
        cell = table.cell(0, j)
        cell.text = ''
        par = cell.paragraphs[0]
        par.paragraph_format.space_before = Pt(2)
        par.paragraph_format.space_after = Pt(2)
        add_inline(par, cell_text.strip(), size=9.5, bold=True, font=HEAD_FONT)
        shade(cell, 'F2F5F8')
    for i, row in enumerate(body, start=1):
        for j in range(len(header)):
            cell = table.cell(i, j)
            cell.text = ''
            par = cell.paragraphs[0]
            par.paragraph_format.space_before = Pt(2)
            par.paragraph_format.space_after = Pt(2)
            add_inline(par, (row[j] if j < len(row) else '').strip(), size=9.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def parse(md_text):
    blocks = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith('```'):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(('code', buf))
            continue
        if stripped.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                raw = lines[i].strip().strip('|')
                cells = [c for c in raw.split('|')]
                if not all(re.fullmatch(r':?-{2,}:?', c.strip()) for c in cells if c.strip()):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(('table', rows))
            continue
        m = re.match(r'^(#{1,4})\s+(.*)$', stripped)
        if m:
            blocks.append(('h', (len(m.group(1)), m.group(2))))
            i += 1
            continue
        if stripped == '---':
            blocks.append(('hr', None))
            i += 1
            continue
        if stripped.startswith('> '):
            blocks.append(('quote', stripped[2:]))
            i += 1
            continue
        m = re.match(r'^(\d+)\.\s+(.*)$', stripped)
        if m:
            blocks.append(('ol', (m.group(1), m.group(2))))
            i += 1
            continue
        if stripped.startswith('- '):
            blocks.append(('ul', stripped[2:]))
            i += 1
            continue
        blocks.append(('p', stripped))
        i += 1
    return blocks


def main():
    md = SRC.read_text(encoding='utf-8')
    blocks = parse(md)

    # 封面：第一个 hr 之前的块
    cover_blocks = []
    rest = blocks
    for idx, blk in enumerate(blocks):
        if blk[0] == 'hr':
            cover_blocks = blocks[:idx]
            rest = blocks[idx + 1:]
            break

    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.4)
    sec.bottom_margin = Cm(2.2)
    sec.left_margin = Cm(2.6)
    sec.right_margin = Cm(2.4)
    add_page_number_footer(sec)

    style = doc.styles['Normal']
    style.font.name = BODY_FONT
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), BODY_FONT)
    style.paragraph_format.line_spacing = 1.45
    style.paragraph_format.space_after = Pt(5)

    build_cover(doc, [b[1][1] if b[0] == 'h' else b[1] for b in cover_blocks if b[0] in ('h', 'p')])

    first_h2 = True
    for blk in rest:
        kind = blk[0]
        if kind == 'h':
            level, text = blk[1]
            if level == 1:
                continue
            if level == 2:
                if not first_h2:
                    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
                first_h2 = False
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(10)
                add_inline(p, text, size=16, bold=True, font=HEAD_FONT)
            elif level == 3:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(10)
                p.paragraph_format.space_after = Pt(5)
                add_inline(p, text, size=12.5, bold=True, font=HEAD_FONT)
            else:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(8)
                p.paragraph_format.space_after = Pt(4)
                add_inline(p, text, size=11, bold=True, font=HEAD_FONT)
        elif kind == 'p':
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(21)
            add_inline(p, blk[1])
        elif kind == 'quote':
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            p.paragraph_format.space_before = Pt(2)
            add_inline(p, blk[1], size=9.5, color=GREY)
        elif kind == 'ul':
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.75)
            p.paragraph_format.first_line_indent = Cm(-0.3)
            add_inline(p, '· ' + blk[1])
        elif kind == 'ol':
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.85)
            p.paragraph_format.first_line_indent = Cm(-0.45)
            add_inline(p, f'{blk[1][0]}. ' + blk[1][1])
        elif kind == 'table':
            emit_table(doc, blk[1])
        elif kind == 'code':
            for row in blk[1]:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.6)
                p.paragraph_format.space_after = Pt(0)
                add_inline(p, row if row.strip() else ' ', size=9, font=MONO_FONT)
        elif kind == 'hr':
            continue

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print('saved', OUT, OUT.stat().st_size)


if __name__ == '__main__':
    main()
