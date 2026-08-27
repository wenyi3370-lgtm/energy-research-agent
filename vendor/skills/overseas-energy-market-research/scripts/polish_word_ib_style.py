# -*- coding: utf-8 -*-
"""
polish_word_ib_style.py — 将 build_template_report.py 的骨架输出一步转换为
投行行业研究风格（IB research style）合规文档。幂等，可重复执行。

对应 SKILL.md "Word 生产常见错误与纠正" 10 条清单：
  1  CSV 行 dump 进正文       → 检测短段+无句号+字段粘连特征，列出告警（内容须人工/上游保证）
  2  模板占位段残留           → 删除"表X-X  本章证据与分析索引"、"数据来源：；…"空占位
  3  来源注重复堆叠           → 连续相同来源注去重（保留第一条）
  4  来源注前缀粘正文         → 拆分"数据来源：xxx"开头的粘连段
  5  图题位置错误             → 重排为 图片段 → 图题段 → 来源注段
  6  段落索引错位             → 本脚本全部按内容定位，禁止固定索引
  7  整段替换截断             → 替换后扫描异常短段（<15 字非来源注段）
  8  LibreOffice 渲染崩溃     → 输出前做 python-docx round-trip 保存
  9  引用重复字/缺失          → 修正"（见图图N-x）"，并为每个图/表补正文引用
 10 表格列名/表题"证据"字样  → 列名"证据/分析项"→"关键事项"、"证据编号"→"来源编号"，
                               表题"证据与分析索引"→"关键数据与来源"

用法:
    python polish_word_ib_style.py <input.docx> [--out <output.docx>]
    # 缺省 --out 时原地覆盖
"""
import argparse
import re
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING

from build_template_report import format_table_captions, format_tables

# ----------------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------------

def ptext(p):
    return p.text.strip()


def is_img(p):
    return bool(p._p.findall(".//" + qn("w:drawing")))


def classify(child, doc):
    if child.tag == qn("w:p"):
        p = Paragraph(child, doc)
        t = ptext(p)
        if p.style.name == "Heading 1":
            return "H1", t, p
        if is_img(p):
            return "IMG", t, p
        if re.match(r"^图\d+-\d+", t):
            return "FIGCAP", t, p
        if re.match(r"^表\d+-\d+", t):
            return "TBLCAP", t, p
        return "P", t, p
    if child.tag == qn("w:tbl"):
        return "TBL", "", Table(child, doc)
    return "OTHER", "", None


def fresh(doc):
    return [classify(c, doc) for c in doc.element.body.iterchildren()]


def set_run_fonts(r, east="宋体", west="Times New Roman", sz=None, bold=None, color=None):
    r.font.name = west
    rPr = r._element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        rf = rPr.makeelement(qn("w:rFonts"), {})
        rPr.insert(0, rf)
    rf.set(qn("w:ascii"), west)
    rf.set(qn("w:hAnsi"), west)
    rf.set(qn("w:eastAsia"), east)
    if sz is not None:
        r.font.size = Pt(sz)
    if bold is not None:
        r.font.bold = bold
    if color is not None:
        r.font.color.rgb = RGBColor.from_string(color)


def set_para_text(p, text, sz=12, centered=False, color=None):
    """整段替换（内容完整版，防止截断）。"""
    for run in p.runs:
        run.text = ""
    r = p.add_run(text)
    set_run_fonts(r, sz=sz, color=color)
    if centered:
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER


def append_text(p, text):
    r = p.add_run(text)
    set_run_fonts(r)


def del_para(p):
    p._p.getparent().remove(p._p)


# ----------------------------------------------------------------------------
# 各步骤（全部内容定位，幂等）
# ----------------------------------------------------------------------------

def step1_skeleton_remnants(doc, report):
    """清单2：删除模板骨架/占位段（循环直到无变化）。"""
    removed = 0
    guard = 0
    while guard < 200:
        seq = fresh(doc)
        changed = False
        for k, t, p in seq:
            s = str(t)
            # 模板四级标题骨架
            if s in ("（1）本章关键问题", "（2）证据、分析与反证", "证据、分析与反证："):
                del_para(p)
                removed += 1
                changed = True
                break
            # 表X-X 占位表题
            if re.match(r"^表X[-\\]?X", s):
                del_para(p)
                removed += 1
                changed = True
                break
            # 空来源注占位
            if s.startswith("数据来源：；") or re.match(r"^数据来源：；(访问/提取日期：；数据类别：；注：。)?$", s):
                del_para(p)
                removed += 1
                changed = True
                break
        if not changed:
            break
        guard += 1
    report["skeleton_removed"] = removed
    return doc


def step2_dedup_source_notes(doc, report):
    """清单3：仅对连续堆叠的相同来源注去重（保留第一条）。
    跨章节各自表后的同文本来源注是合理布局，不得误删。"""
    removed = 0
    changed = True
    guard = 0
    while changed and guard < 100:
        changed = False
        seq = fresh(doc)
        for i in range(len(seq) - 1):
            k0, t0, p0 = seq[i]
            k1, t1, p1 = seq[i + 1]
            if k0 == "P" and k1 == "P" and str(t0) and str(t0) == str(t1) \
                    and str(t0).startswith("数据来源："):
                del_para(p1)
                removed += 1
                changed = True
                break
        guard += 1
    report["dup_src_removed"] = removed
    return doc


TEMPLATE_BODY_PREFIXES = (
    "本节只放置经核验的核心结论。",
    "回答本项目要支持的决策、核心结论、证据置信度",
    "定义地区、产品、客户、时间、币种、税费、数据类别、来源优先级",
    "覆盖供电可靠性、分时电价、上网规则、补贴、并网、标准、认证",
    "建立市场定义、历史规模、预测、TAM/SAM/SOM",
    "覆盖家庭、移动/离网、阳台光储、V2G/V2H、停电、出行和支付能力",
    "分析电池、逆变器、双向功率、接口、协议、EMS/VPP、安全",
    "按精确型号、区域版本、配置、认证和产品链接",
    "比较价格口径、促销、线上线下渠道、安装商、售后",
    "先保存原始评论，再进行主题编码",
    "呈现假设、符号、公式、约束、模型结果",
    "对标项目业主、场景、规模、技术路线、平台、运营模式",
    "输出目标客户、SKU、容量/功率、协议认证、价格带",
    "给出风险、优先级、里程碑、试点、负责人",
    "集中列示来源台账、模型假设、证据冲突、原始数据",
)


def step1b_remove_template_body(doc, report):
    """删除模板占位正文段（骨架说明文字，非真实内容）。"""
    removed = 0
    changed = True
    guard = 0
    while changed and guard < 100:
        changed = False
        for k, t, p in fresh(doc):
            s = str(t)
            if k == "P" and s and s.startswith(TEMPLATE_BODY_PREFIXES):
                del_para(p)
                removed += 1
                changed = True
                break
        guard += 1
    report["template_body_removed"] = removed
    return doc


def step3_neutralize_table_headers(doc, report):
    """清单10：表头/表题中性化。"""
    renamed = 0
    for tbl in doc.tables:
        for cell in tbl.rows[0].cells:
            t = cell.text.strip()
            new = None
            if t == "证据/分析项":
                new = "关键事项"
            elif t == "证据编号":
                new = "来源编号"
            elif t == "来源ID":
                new = "来源编号"
            if new:
                p0 = cell.paragraphs[0]
                for run in p0.runs:
                    run.text = ""
                r = p0.add_run(new)
                set_run_fonts(r, sz=9, bold=True)
                renamed += 1
    # 表题
    for p in doc.paragraphs:
        s = p.text.strip()
        m = re.match(r"^(表\d+-\d+)\s+", s)
        if m and ("证据与分析索引" in s or "证据索引" in s):
            set_para_text(p, f"{m.group(1)} 本章关键数据与来源", sz=10.5, centered=True)
            renamed += 1
    report["headers_neutralized"] = renamed
    return doc


def step4_fix_figure_order(doc, report):
    """清单5：图题/来源注移到图片之后（IMG → FIGCAP → 来源注）。"""
    fixed = 0
    for _ in range(5):
        seq = fresh(doc)
        changed = False
        for i in range(len(seq) - 2):
            k0, t0, p0 = seq[i]
            k1, t1, p1 = seq[i + 1]
            k2, t2, p2 = seq[i + 2]
            # [FIGCAP, IMG, ...] → 图题移到图片后
            if k0 == "FIGCAP" and k1 == "IMG":
                p1._p.addnext(p0._p)
                fixed += 1
                changed = True
                break
            # [P来源注, FIGCAP, IMG] → 来源注移到图片后
            if k0 == "P" and str(t0).startswith("数据来源：") and k1 == "FIGCAP" and k2 == "IMG":
                p2._p.addnext(p0._p)
                fixed += 1
                changed = True
                break
        if not changed:
            break
    report["fig_order_fixed"] = fixed
    return doc


def step5_clean_evidence_traces(doc, report):
    """清单1/4/9：正文清理——粘连来源注拆分、转义符、重复引用字。"""
    fixed = 0
    for k, t, p in fresh(doc):
        if k != "P":
            continue
        s = str(t)
        if not s:
            continue
        new_s = s
        # 来源注前缀粘正文（"数据来源：项目组分析从客户收入看，…"）→ 拆掉前缀
        # 仅当后续正文足够长（>40 字）且含句号时才拆分，避免误伤图表下方的短来源注
        m = re.match(r"^(数据来源：[^。；]{2,20}?)([\u4e00-\u9fff].{40,}。)", s)
        if m:
            new_s = m.group(2)
            fixed += 1
        # 转义符
        new_s = new_s.replace(r"\-", "-").replace(r"\.", ".").replace(r"\+", "+")
        # 引用重复字（"（见图图0-1）"→"（见图0-1）"）
        new_s = re.sub(r"（见图图(\d+-\d+)）", r"（见图\1）", new_s)
        new_s = re.sub(r"（见表表(\d+-\d+)）", r"（见表\1）", new_s)
        if new_s != s:
            set_para_text(p, new_s)
            fixed += 1
    report["evidence_cleaned"] = fixed
    return doc


def step6_fix_references(doc, report):
    """清单9：确保每个图/表在正文被引用（见图N-x / 见表N-x）。"""
    seq = fresh(doc)
    body_idx = [i for i, (k, t, p) in enumerate(seq) if k == "P" and str(t) and not str(t).startswith("数据来源：")]
    added = 0
    for i, (k, t, p) in enumerate(seq):
        if k == "FIGCAP":
            m = re.match(r"^(图\d+-\d+)", str(t))
            if not m:
                continue
            ref = "（见图" + m.group(1)[1:] + "）"
            # 向前找最近正文段
            for j in range(i - 1, -1, -1):
                if seq[j][0] == "P" and str(seq[j][1]) and not str(seq[j][1]).startswith("数据来源："):
                    if ref not in seq[j][2].text:
                        append_text(seq[j][2], ref)
                        added += 1
                    break
                if seq[j][0] in ("H1", "TBL", "IMG"):
                    break
        elif k == "TBLCAP":
            m = re.match(r"^(表\d+-\d+)", str(t))
            if not m:
                continue
            ref = "（见表" + m.group(1)[1:] + "）"
            for j in range(i - 1, -1, -1):
                if seq[j][0] == "P" and str(seq[j][1]) and not str(seq[j][1]).startswith("数据来源："):
                    if ref not in seq[j][2].text:
                        append_text(seq[j][2], ref)
                        added += 1
                    break
                if seq[j][0] in ("H1", "TBL", "IMG"):
                    break
    report["refs_added"] = added
    return doc


def step7_short_para_scan(doc, report):
    """清单7：扫描异常短段（告警，不删除）。"""
    short = []
    for k, t, p in fresh(doc):
        s = str(t)
        if k == "P" and s and len(s) < 15 and not s.startswith("数据来源") and not re.match(r"^[图表]\d", s):
            short.append(s[:30])
    report["short_paras"] = short
    return doc


# 图文件名 → (章号, 图题)。章号 0 = 核心结论（无编号章）。
DEFAULT_FIGURE_MAP = {
    "fig1_executive_summary": (1, "BESS 市场规模与增长（2025–2033）"),
    "fig2_methodology": (2, "调研方法与数据体系"),
    "fig10_timeline": (3, "政策与补贴时间轴（2009–FY2026）"),
    "fig_electricity_fit_v2": (3, "FIT 到期与自消费经济性"),
    "fig_bess_market_v2": (0, "核心结论与市场总览"),
    "fig_btm_segmentation_v2": (4, "BTM 户储细分与增长"),
    "fig4_customer_needs": (5, "客户需求与购买驱动"),
    "fig_self_consumption_v2": (5, "典型家庭自消费率对比（东京 4 人家庭）"),
    "fig6_product_architecture": (6, "10kWh 户用光储系统架构（建议产品定义）"),
    "fig5_competitor_radar": (7, "竞品多维能力对比"),
    "fig6_price_capacity": (8, "价格–容量分布"),
    "fig_price_comparison_v2": (8, "竞品单 kWh 价格对比"),
    "fig7_channel_coverage": (8, "渠道覆盖对比"),
    "fig9_review_topics": (9, "用户评论主题频次与严重度"),
    "fig_payback_v2": (10, "投资回收期测算（补贴敏感性）"),
    "fig11_v2h_vpp": (11, "V2H 与 VPP 参与示意（FY2026 低压市场准入）"),
    "fig8_swot_matrix": (12, "SWOT 与机会矩阵"),
    "fig9_risk_matrix": (13, "风险矩阵"),
    "fig14_source_structure": (14, "数据来源结构"),
}
CH_NUM_CN = {0: "核心结论", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六",
             7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二", 13: "十三", 14: "十四"}


def step9_distribute_figures(doc, report, figure_map=None):
    """把图块（IMG+FIGCAP+来源注）按文件名映射移动到对应章节，重编号并人性化图题。
    未映射的图保留原位并计入 figs_not_mapped 告警（不猜测章节）。"""
    if figure_map is None:
        figure_map = DEFAULT_FIGURE_MAP
    seq = fresh(doc)

    # 收集图块：每个 FIGCAP 及其前导 IMG、后续来源注；只处理生成器原样图题（含 fig 文件名）
    blocks = []  # (img_p, figcap_p, src_p, figkey, current_label)
    for i, (k, t, p) in enumerate(seq):
        if k == "FIGCAP" and "fig" in str(t):
            img_p = seq[i - 1][2] if i > 0 and seq[i - 1][0] == "IMG" else None
            src_p = seq[i + 1][2] if i + 1 < len(seq) and seq[i + 1][0] == "P" and str(seq[i + 1][1]).startswith("数据来源：") else None
            blocks.append((img_p, p, src_p, str(t)))
    if not blocks:
        report["figs_distributed"] = 0
        report["figs_not_mapped"] = []
        return doc

    # 章节标题 → 段落对象
    h1_map = {}  # 章号 -> H1 段落
    for k, t, p in fresh(doc):
        if k == "H1":
            s = str(t)
            if s.startswith("核心结论"):
                h1_map[0] = p
            else:
                m = re.match(r"^([一二三四五六七八九十]+)、", s)
                if m:
                    for num, cn in CH_NUM_CN.items():
                        if num and cn == m.group(1):
                            h1_map[num] = p
                            break
    # 章内序号
    chapter_counter = {}

    # 移除图块并记录
    moved = 0
    unmapped = []
    for img_p, cap_p, src_p, label in blocks:
        figkey = label
        m = re.search(r"fig[\w_]+", label)
        if m:
            figkey = m.group(0)
        if figkey not in figure_map:
            # 未映射：告警并保留原位（不猜测章节，避免错误分布）
            unmapped.append(figkey)
            continue
        ch, title = figure_map[figkey]
        chapter_counter[ch] = chapter_counter.get(ch, 0) + 1
        new_no = f"图{ch}-{chapter_counter[ch]}"
        # 移动元素：图块整体移到章节 H1 之后（若该章无正文，直接跟 H1）
        anchor = h1_map.get(ch)
        if anchor is None:
            unmapped.append(figkey + "(无章节锚点)")
            continue
        # 顺序：先插 src，再插 cap，最后插 img → 最终 anchor 后为 img, cap, src
        if src_p is not None:
            anchor._p.addnext(src_p._p)
        anchor._p.addnext(cap_p._p)
        if img_p is not None:
            anchor._p.addnext(img_p._p)
        # 更新图题
        set_para_text(cap_p, f"{new_no} {title}", sz=10.5, centered=True)
        moved += 1
    report["figs_distributed"] = moved
    report["figs_not_mapped"] = unmapped
    return doc


def _chapter_number(heading: str):
    if heading.startswith("核心结论"):
        return 0
    match = re.match(r"^([一二三四五六七八九十]+)、", heading)
    return next((number for number, cn in CH_NUM_CN.items() if number and match and cn == match.group(1)), None)


def _format_table_caption(doc, paragraph, text):
    try:
        paragraph.style = doc.styles["Table Caption"]
    except KeyError:
        paragraph.style = doc.styles["Normal"]
    set_para_text(paragraph, text, sz=10.5, centered=True)
    pf = paragraph.paragraph_format
    pf.space_before = Pt(6)
    pf.space_after = Pt(0)
    pf.keep_with_next = True
    pf.keep_together = True
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    pf.line_spacing = 1.0


def step10_normalize_table_captions(doc, report):
    """Enforce one—and only one—caption immediately before every report table.

    The old implementation searched the whole document for a matching number.
    That allowed a sequence such as ``caption → table → caption → caption →
    table`` to pass and produced repeated table notes. This pass operates in
    document order, keeps the nearest useful caption, removes surplus captions,
    and renumbers every table inside its chapter.
    """
    added = removed = renumbered = 0
    current_chapter = None
    chapter_counts = {}
    for kind, text, item in list(fresh(doc)):
        # Only structural chapter headings may reset numbering. Body prose can
        # legitimately start with words such as "核心结论" and must not be
        # mistaken for a new chapter.
        if kind == "H1":
            current_chapter = _chapter_number(str(text))
            continue
        if kind != "TBL" or current_chapter is None:
            continue  # cover/control tables intentionally have no caption
        chapter_counts[current_chapter] = chapter_counts.get(current_chapter, 0) + 1
        desired_number = f"表{current_chapter}-{chapter_counts[current_chapter]}"

        # Collect the contiguous caption run immediately before this table.
        caption_elements = []
        previous = item._tbl.getprevious()
        while previous is not None and previous.tag == qn("w:p"):
            paragraph = Paragraph(previous, doc)
            if not re.match(r"^表\d+-\d+", ptext(paragraph)):
                break
            caption_elements.append(paragraph)
            previous = previous.getprevious()
        caption_elements.reverse()

        if caption_elements:
            meaningful = [
                paragraph for paragraph in caption_elements
                if "本章关键数据与来源" not in ptext(paragraph)
            ]
            keeper = meaningful[-1] if meaningful else caption_elements[-1]
            for paragraph in caption_elements:
                if paragraph is keeper:
                    continue
                del_para(paragraph)
                removed += 1
            suffix = re.sub(r"^表\d+-\d+\s*", "", ptext(keeper)).strip()
            suffix = suffix or "本章关键数据与来源"
            desired_text = f"{desired_number} {suffix}"
            if ptext(keeper) != desired_text:
                renumbered += 1
            _format_table_caption(doc, keeper, desired_text)
            # If the useful caption was not nearest, move it next to the table.
            item._tbl.addprevious(keeper._p)
        else:
            caption = doc.add_paragraph()
            _format_table_caption(doc, caption, f"{desired_number} 本章关键数据与来源")
            item._tbl.addprevious(caption._p)
            added += 1

    report["table_captions_added"] = added
    report["duplicate_table_captions_removed"] = removed
    report["table_captions_renumbered"] = renumbered
    return doc


def step5b_normalize_source_notes(doc, report):
    """来源注内容规范化：去掉 CSV 文件名/证据编号，改为自然来源描述。"""
    fixed = 0
    for k, t, p in fresh(doc):
        if k != "P":
            continue
        s = str(t)
        if not s.startswith("数据来源："):
            continue
        new_s = s
        new_s = re.sub(r"（S 编号见 00_Source_Ledger 台账）", "", new_s)
        new_s = re.sub(r"来源台账（00_Source_Ledger\.csv）", "项目来源台账", new_s)
        new_s = re.sub(r"\d{2}_[A-Za-z_]+\.csv（[^）]*）", "项目调研数据", new_s)
        new_s = re.sub(r"\d{2}_[A-Za-z_]+\.csv", "项目调研数据", new_s)
        new_s = re.sub(r"[（(](?:S|C|R|P|A|D)\d{3}(?:[-–][A-Z]?\d{3})?[)）]", "", new_s)
        new_s = re.sub(r"；更新日期：[^。；]*", "", new_s)
        # 统一尾部：去除多余句号/分号后只保留一个句号
        new_s = re.sub(r"[。；\s]+$", "", new_s)
        new_s = new_s + "。"
        if new_s != s:
            for run in p.runs:
                run.text = ""
            r = p.add_run(new_s)
            set_run_fonts(r, sz=9, color="808080")
            fixed += 1
    report["source_notes_normalized"] = fixed
    return doc


def step11_normalize_body_format(doc, report):
    """正文段格式规范（硬性，2026-08-07 教训固化）：固定 22pt 行距（line=440 exact）
    + 首行缩进 2 字符（firstLineChars=200，磅值 firstLine=480 作兼容兜底）。

    只处理正文段（classify 为 P 的 Normal 段），跳过封面/标题/图题/来源注/图片段/表格单元格。
    幂等：已符合的段落不会重复计数或改动。
    """
    fixed = 0
    for k, t, p in fresh(doc):
        if k != "P":
            continue
        s = str(t).strip()
        if not s:
            continue
        if p.style.name in {"Cover Label", "Title", "Subtitle", "Table Caption"}:
            continue
        if p.style.name.startswith("Heading"):
            continue
        if s.startswith("数据来源："):
            continue
        if is_img(p):
            continue
        pPr = p._p.get_or_add_pPr()
        sp = pPr.get_or_add_spacing()
        if sp.get(qn("w:line")) != "440" or sp.get(qn("w:lineRule")) != "exact":
            sp.set(qn("w:line"), "440")
            sp.set(qn("w:lineRule"), "exact")
            fixed += 1
        ind = pPr.get_or_add_ind()
        if ind.get(qn("w:firstLineChars")) != "200":
            ind.set(qn("w:firstLineChars"), "200")
            if not ind.get(qn("w:firstLine")):
                ind.set(qn("w:firstLine"), "480")
            fixed += 1
    report["body_format_normalized"] = fixed
    return doc


def step11b_normalize_figure_paragraphs(doc, report):
    """Make inline figures impossible to clip through inherited fixed spacing.

    A drawing may be several inches high, so ``lineRule=exact`` is invalid on
    either the paragraph or its style.  Set both layers to single/auto and
    retain the image/caption pair on one page when space permits.
    """
    fixed = 0
    try:
        style = doc.styles["Figure Image"]
        pf = style.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pf.line_spacing = 1.0
        pf.space_before = Pt(6)
        pf.space_after = Pt(0)
        pf.keep_with_next = True
        pf.keep_together = True
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fixed += 1
    except KeyError:
        pass
    for _, _, paragraph in fresh(doc):
        if not isinstance(paragraph, Paragraph):
            continue
        if not is_img(paragraph):
            continue
        pf = paragraph.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pf.line_spacing = 1.0
        pf.space_before = Pt(6)
        pf.space_after = Pt(0)
        pf.keep_with_next = True
        pf.keep_together = True
        pf.first_line_indent = Pt(0)
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fixed += 1
    report["figure_paragraphs_normalized"] = fixed
    return doc


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Polish Word report to IB research style (idempotent)")
    ap.add_argument("docx", help="input .docx")
    ap.add_argument("--out", help="output .docx (default: in-place)")
    ap.add_argument("--figure-map", help="JSON file: {fig_filename_keyword: [chapter_num, title]}; "
                                          "defaults to built-in map; unmapped figures keep position and get a warning")
    args = ap.parse_args()

    figure_map = DEFAULT_FIGURE_MAP
    if args.figure_map:
        import json
        with open(args.figure_map, encoding="utf-8") as f:
            figure_map = {k: (int(v[0]), v[1]) for k, v in json.load(f).items()}

    doc = Document(args.docx)
    report = {}

    doc = step1_skeleton_remnants(doc, report)
    doc = step1b_remove_template_body(doc, report)
    doc = step2_dedup_source_notes(doc, report)
    doc = step3_neutralize_table_headers(doc, report)
    # Repair the legacy four-values-into-five-columns bug in 表0-1. Older
    # reports placed the conclusion in the narrow 序号 column and left the
    # final confidence column empty, producing vertical one-character wraps.
    repaired = 0
    if len(doc.tables) > 1:
        core = doc.tables[1]
        headers = [cell.text.strip() for cell in core.rows[0].cells] if core.rows else []
        if len(headers) == 5 and headers[0] == "序号" and "核心结论" in headers[1]:
            for sequence, row in enumerate(core.rows[1:], start=1):
                values = [cell.text.strip() for cell in row.cells]
                if len(values) == 5 and not values[0].isdigit() and not values[4] and any(values[:4]):
                    migrated = [str(sequence), values[0], values[1], "", "；".join(value for value in values[2:4] if value)]
                    for cell, value in zip(row.cells, migrated):
                        cell.text = value
                    repaired += 1
    report["legacy_core_rows_repaired"] = repaired
    doc = step9_distribute_figures(doc, report, figure_map=figure_map)
    doc = step10_normalize_table_captions(doc, report)
    doc = step4_fix_figure_order(doc, report)
    doc = step5_clean_evidence_traces(doc, report)
    doc = step5b_normalize_source_notes(doc, report)
    doc = step6_fix_references(doc, report)
    doc = step7_short_para_scan(doc, report)
    doc = step11_normalize_body_format(doc, report)
    doc = step11b_normalize_figure_paragraphs(doc, report)
    # Finalize every table on every run. Historical reports may already be
    # structurally clean while retaining a single black header run or stale
    # border from an older builder; the polisher must close that gap itself.
    format_tables(doc)
    report["tables_reformatted"] = len(doc.tables)
    report["table_captions_locked"] = format_table_captions(doc)

    out = args.out or args.docx
    doc.save(out)
    # round-trip（清单8）
    doc2 = Document(out)
    doc2.save(out)

    print("polish 完成:", out)
    for k, v in report.items():
        if k == "short_paras":
            print(f"  short_paras(告警): {v if v else '无 ✓'}")
        else:
            print(f"  {k}: {v}")
    print("注意：CSV 行 dump（清单1）与骨架标签段文风改写依赖上游 fill/写作，脚本只负责结构与可机检项。")


if __name__ == "__main__":
    main()
