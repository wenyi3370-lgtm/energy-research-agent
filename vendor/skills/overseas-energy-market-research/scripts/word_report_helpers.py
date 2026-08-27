# -*- coding: utf-8 -*-
"""Helper functions for overseas-energy-market-research Word report generation.

This module provides functions to:
1. Strip all template placeholder chapters from the template
2. Apply proper three-line table formatting
3. Set heading styles per format-and-visual-style.md
4. Add properly formatted tables with captions

Usage:
    from word_report_helpers import strip_all_template_chapters, add_three_line_table
"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def strip_all_template_chapters(doc):
    """删除模板中所有占位章节内容，只保留封面和基本结构。
    
    The template has 14 placeholder chapters with empty tables and placeholder text.
    This function removes all H1 sections while preserving w:sectPr (page layout).
    """
    body = doc.element.body
    children = list(body.iterchildren())
    
    # Find the first H1 heading
    first_h1_idx = None
    for i, el in enumerate(children):
        if _is_heading_1_el(el):
            first_h1_idx = i
            break
    
    if first_h1_idx is None:
        return 0
    
    # Remove everything from the first H1 to the end, but preserve sectPr
    removed = 0
    for el in children[first_h1_idx:]:
        if el.tag == qn('w:sectPr'):
            continue
        body.remove(el)
        removed += 1
    
    return removed


def _is_heading_1_el(el):
    """Check if element is a Heading 1 paragraph."""
    if el.tag != qn('w:p'):
        return False
    ppr = el.find(qn('w:pPr'))
    if ppr is None:
        return False
    pstyle = ppr.find(qn('w:pStyle'))
    return pstyle is not None and pstyle.get(qn('w:val')) == 'Heading1'


def set_run_font(run, east_asia='SimSun', size=12, bold=False, color=None):
    """Set font properties for a run."""
    run.font.name = 'Times New Roman'
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:ascii'), 'Times New Roman')
    rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    rFonts.set(qn('w:eastAsia'), east_asia)


def add_three_line_table(doc, caption, headers, rows, source=None):
    """Add a properly formatted three-line table with caption.
    
    Follows format-and-visual-style.md:
    - Top/bottom borders: 1.5pt black #000000
    - Header bottom border: 1pt deep blue #1B365D
    - Header shading: #D9E2EC
    - No left/right/insideH/insideV borders
    - All cells vertically centered
    - All cells horizontally centered
    - No first-line indent
    - Single line spacing
    - Font: 宋体小五 9pt + Times New Roman
    - Header: bold, deep blue text
    """
    # Table caption
    if caption:
        cp = doc.add_paragraph()
        cr = cp.add_run(caption)
        set_run_font(cr, 'SimSun', 10, True)
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.paragraph_format.space_before = Pt(6)
        cp.paragraph_format.space_after = Pt(4)
        # keep_with_next and keep_together
        pPr = cp._element.get_or_add_pPr()
        pPr.append(OxmlElement('w:keepNext'))
        pPr.append(OxmlElement('w:keepLines'))
        # Set style to Table Caption if available
        try:
            cp.style = doc.styles['Table Caption']
        except KeyError:
            pass

    # Create table
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Apply three-line borders
    tblPr = t._tbl.tblPr
    for existing in list(tblPr.findall(qn('w:tblBorders'))):
        tblPr.remove(existing)
    borders = OxmlElement('w:tblBorders')
    for edge, sz in (('top', 12), ('bottom', 12)):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), str(sz))
        el.set(qn('w:color'), '000000')
        borders.append(el)
    for edge in ('left', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'none')
        el.set(qn('w:sz'), '0')
        el.set(qn('w:color'), 'FFFFFF')
        borders.append(el)
    tblW = tblPr.find(qn('w:tblW'))
    if tblW is not None:
        tblW.addnext(borders)
    else:
        tblPr.append(borders)

    # Header row
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = h
        cell.vertical_alignment = 1  # CENTER
        # Apply header cell borders and shading
        tcPr = cell._tc.get_or_add_tcPr()
        for existing in list(tcPr.findall(qn('w:tcBorders'))):
            tcPr.remove(existing)
        for existing in list(tcPr.findall(qn('w:shd'))):
            tcPr.remove(existing)
        tc_borders = OxmlElement('w:tcBorders')
        for edge in ('top', 'left', 'right', 'bottom'):
            el = OxmlElement(f'w:{edge}')
            el.set(qn('w:val'), 'none')
            el.set(qn('w:sz'), '0')
            el.set(qn('w:color'), 'FFFFFF')
            tc_borders.append(el)
        # Header bottom border: 1pt deep blue
        bottom = tc_borders.find(qn('w:bottom'))
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '8')
        bottom.set(qn('w:color'), '1B365D')
        tcPr.append(tc_borders)
        # Header shading
        shading = OxmlElement('w:shd')
        shading.set(qn('w:val'), 'clear')
        shading.set(qn('w:color'), 'auto')
        shading.set(qn('w:fill'), 'D9E2EC')
        tcPr.append(shading)
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            for run in p.runs:
                set_run_font(run, 'SimSun', 9, True)
                run.font.color.rgb = RGBColor(27, 54, 93)

    # Data rows
    for r_idx, row_data in enumerate(rows):
        for c_idx, val in enumerate(row_data):
            cell = t.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)
            cell.vertical_alignment = 1  # CENTER
            # Apply cell borders
            tcPr = cell._tc.get_or_add_tcPr()
            for existing in list(tcPr.findall(qn('w:tcBorders'))):
                tcPr.remove(existing)
            tc_borders = OxmlElement('w:tcBorders')
            for edge in ('top', 'left', 'right', 'bottom'):
                el = OxmlElement(f'w:{edge}')
                el.set(qn('w:val'), 'none')
                el.set(qn('w:sz'), '0')
                el.set(qn('w:color'), 'FFFFFF')
                tc_borders.append(el)
            tcPr.append(tc_borders)
            for p in cell.paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.first_line_indent = Pt(0)
                p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
                for run in p.runs:
                    set_run_font(run, 'SimSun', 9, False)

    if source:
        add_source_note(doc, f'数据来源：{source}')

    return t


def add_source_note(doc, text):
    """Add a source note paragraph."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    set_run_font(run, 'SimSun', 9, False)
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    p.paragraph_format.line_spacing = Pt(16)
    return p


def generate_chart_png(chart_func, filename, charts_dir, title='', figsize=(8, 5)):
    """Generate a chart PNG using matplotlib and save to charts_dir.
    
    Args:
        chart_func: A callable that takes (fig, ax) and draws the chart
        filename: Output filename (e.g., 'fig1_market_size.png')
        charts_dir: Directory to save the PNG
        title: Chart title
        figsize: Figure size tuple
    
    Returns:
        Path to the saved PNG file
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import os
    
    plt.rcParams['axes.unicode_minus'] = False
    # v9: matplotlib CJK family comes from the shared multi-level resolver
    # (scripts/common/fonts.py) — no per-module candidate list.
    from common.fonts import resolve_cjk_font_family
    _cjk = resolve_cjk_font_family()
    if _cjk:
        plt.rcParams['font.sans-serif'] = [_cjk]
    
    os.makedirs(charts_dir, exist_ok=True)
    
    fig, ax = plt.subplots(figsize=figsize)
    chart_func(fig, ax)
    
    if title:
        ax.set_title(title, fontsize=16, fontweight='bold', color='#0F172A', pad=15)
    
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#94A3B8')
    ax.spines['bottom'].set_color('#94A3B8')
    ax.tick_params(colors='#64748B')
    
    plt.tight_layout()
    path = os.path.join(charts_dir, filename)
    plt.savefig(path, dpi=200, bbox_inches='tight', facecolor='#FFFFFF')
    plt.close()
    
    return path


def insert_charts_to_report(doc, charts_dir, section_marker, caption_chapter=3):
    """Insert chart PNGs into Word document at specified section.
    
    Args:
        doc: python-docx Document object
        charts_dir: Directory containing fig*.png files
        section_marker: Section heading text to insert charts after
        caption_chapter: Chapter number for figure captions (图X-N)
    
    Returns:
        Number of charts inserted
    """
    from pathlib import Path
    
    charts_path = Path(charts_dir)
    if not charts_path.exists():
        return 0
    
    pngs = sorted(charts_path.glob('fig*.png'))
    if not pngs:
        return 0
    
    # Find section anchor
    anchor_idx = None
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip() == section_marker:
            anchor_idx = i + 1
            break
    
    if anchor_idx is None:
        print(f'  [warn] Section marker "{section_marker}" not found, skipping {len(pngs)} charts')
        return 0
    
    anchor = doc.paragraphs[anchor_idx]._p
    
    for idx, png in enumerate(pngs, start=1):
        # Insert image paragraph
        p_img = doc.add_paragraph()
        run = p_img.add_run()
        run.add_picture(str(png), width=Inches(5.2))
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_img.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p_img.paragraph_format.space_before = Pt(6)
        p_img.paragraph_format.space_after = Pt(0)
        
        # Try to set Figure Image style
        try:
            p_img.style = doc.styles['Figure Image']
        except KeyError:
            pass
        
        # Insert caption
        p_cap = doc.add_paragraph()
        p_cap.paragraph_format.space_before = Pt(0)
        p_cap.paragraph_format.space_after = Pt(6)
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p_cap.add_run(f'图{caption_chapter}-{idx} {png.stem}')
        r.font.size = Pt(10.5)
        set_run_font(r, 'SimSun', 10.5, False)
        
        # Insert source note
        p_note = doc.add_paragraph()
        p_note.paragraph_format.space_after = Pt(12)
        r2 = p_note.add_run('数据来源：来源台账（00_Source_Ledger.csv）；推测数据已标注（推测）。')
        r2.font.size = Pt(9)
        r2.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        
        # Move elements after anchor
        anchor.addnext(p_img._element)
        p_img._element.addnext(p_cap._element)
        p_cap._element.addnext(p_note._element)
        anchor = p_note._element
    
    return len(pngs)
