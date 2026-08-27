# -*- coding: utf-8 -*-
"""
verify_word_ib_style.py — 投行研报风格机检验证（gate），输出 PASS/FAIL 报告。

覆盖 SKILL.md "Word 生产常见错误与纠正" 10 条清单中所有可机检项：
  1  CSV 行 dump 进正文（字段粘连短段）
  2  模板占位残留（表X-X、数据来源：；、[[xxx]]）
  3  来源注连续堆叠
  4  来源注前缀粘正文
  5  图题位置（IMG → 图题 → 来源注）
  6  （索引问题属过程性，无法静态机检——见 8/9 的运行时约束说明）
  7  异常短段（<15 字，疑似截断）
  9  引用重复字（见图图N-x）与图表引用缺失
 10 表头/表题"证据"字样
额外机检：
  - 骨架标题残留（"（1）本章关键问题"等）
  - 标签前缀段（"小结：""数据引用：""看宏观："等）
  - 证据编号/CSV 文件名/转义符入正文
  - 每章图表覆盖（每章 ≥1 图 + 表题存在）
  - 重复章节标题

用法:
    python verify_word_ib_style.py <docx> [--out <report.md>]
    退出码 0 = 全部通过；1 = 存在 FAIL 项
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


def ptext(p):
    return p.text.strip()


def all_bold(p):
    """全加粗短段是加粗引导句/小标题而非截断（与标题样式同等待遇）。"""
    runs = [r for r in p.runs if r.text.strip()]
    return bool(runs) and all(r.bold for r in runs)


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


def main():
    ap = argparse.ArgumentParser(description="Verify Word report IB-research style (gate)")
    ap.add_argument("docx", help="input .docx")
    ap.add_argument("--out", help="report .md path (default: stdout)")
    args = ap.parse_args()

    doc = Document(args.docx)
    seq = fresh(doc)
    results = []  # (check_id, name, status, detail)

    def add(cid, name, status, detail=""):
        results.append((cid, name, status, detail))

    body_texts = [str(t) for k, t, p in seq if k == "P"]

    # ---- 1. CSV 行 dump ----
    # 特征：短段、无句号结尾、字段粘连（数值/机构名紧跟）、且不是图表下方来源注
    dump_pats = [r"Mark & Spark Solutions", r"Credence Research", r"Grand View Research",
                 r"官方零售", r"授权安装商", r"质保承诺", r"Energy-Storage"]
    dumps = []
    for i, (k, t, p) in enumerate(seq):
        s = str(t)
        # 跳过图表下方的来源注段（紧跟 IMG/FIGCAP/TBL，9pt 灰色短段）
        prev = seq[i - 1] if i > 0 else (None, "", None)
        if prev[0] in ("IMG", "FIGCAP", "TBL"):
            continue
        if k == "P" and s and len(s) < 130 and not s.endswith("。") \
                and not s.startswith("数据来源") \
                and any(re.search(pat, s) for pat in dump_pats):
            dumps.append(f"[{i}]{s[:30]}")
    add(1, "CSV 行 dump", "FAIL" if dumps else "PASS", "; ".join(dumps[:5]))

    # ---- 2. 模板占位 ----
    ph = []
    for i, (k, t, p) in enumerate(seq):
        s = str(t)
        if k == "P" and re.search(r"表X[-\\]?X|数据来源：；|\[\[|\]\]", s):
            ph.append(f"[{i}]{s[:30]}")
    add(2, "模板占位残留", "FAIL" if ph else "PASS", "; ".join(ph[:5]))

    # ---- 3. 来源注连续堆叠 ----
    stack = []
    for i in range(len(seq) - 1):
        if seq[i][0] == "P" and seq[i + 1][0] == "P" \
                and str(seq[i][1]) and str(seq[i][1]) == str(seq[i + 1][1]) \
                and str(seq[i][1]).startswith("数据来源："):
            stack.append(f"[{i}]")
    add(3, "来源注堆叠", "FAIL" if stack else "PASS", "; ".join(stack[:5]))

    # ---- 4. 来源注前缀粘正文 ----
    # 特征：以"数据来源："开头但后续是长正文（>60字且含句号），且不是图表下方来源注
    sticky = []
    for i, (k, t, p) in enumerate(seq):
        s = str(t)
        if k == "P" and s.startswith("数据来源：") and len(s) > 60:
            prev = seq[i - 1] if i > 0 else (None, "", None)
            if prev[0] not in ("IMG", "FIGCAP", "TBL"):
                sticky.append(f"[{i}]")
    add(4, "来源注粘正文", "FAIL" if sticky else "PASS", "; ".join(sticky[:5]))

    # ---- 5. 图题位置 ----
    bad5 = [f"[{i}]" for i in range(len(seq) - 1)
            if seq[i][0] == "IMG" and seq[i + 1][0] != "FIGCAP"]
    add(5, "图题位置", "FAIL" if bad5 else "PASS", "; ".join(bad5[:5]))

    # ---- 7. 异常短段 ----
    # 排除封面标题行与图表题；标题样式（Title/Heading*）不是正文段，
    # 与 polish step11 跳过 Heading* 的语义保持一致；以冒号收尾的引导句
    # 与“（全文完）”尾注是完整语句而非截断。
    short = [f"[{i}]'{str(seq[i][1])}'" for i, (k, t, p) in enumerate(seq)
             if k == "P" and str(t) and len(str(t)) < 15
             and not str(p.style.name).startswith(("Heading", "Title", "Subtitle"))
             and not all_bold(p)
             and not str(t).startswith("数据来源") and not re.match(r"^[图表]\d", str(t))
             and not str(t).startswith("（全文完）")
             and not str(t).endswith(("：", ":"))
             and str(t) not in ("研究院  |  MARKET & PRODUCT INTELLIGENCE",)
             and not re.match(r"^(日本户用储能市场深度调研报告|政策 · 市场)", str(t))]
    add(7, "异常短段", "FAIL" if short else "PASS", "; ".join(short[:5]))

    # ---- 骨架标题 ----
    skel = [f"[{i}]" for i, (k, t, p) in enumerate(seq)
            if k == "P" and str(t) in ("（1）本章关键问题", "（2）证据、分析与反证", "证据、分析与反证：")]
    add("S1", "骨架标题残留", "FAIL" if skel else "PASS", "; ".join(skel[:5]))

    # ---- 标签前缀段 ----
    labels = ("小结：", "数据引用：", "证据支撑：", "反证与限制：", "看宏观：", "看行业：",
              "看客户：", "看自己：", "模型引用：", "参数引用：", "策略依据：", "行动依据：", "缺口登记：")
    lab = [f"[{i}]" for i, (k, t, p) in enumerate(seq)
           if k == "P" and str(t).startswith(labels)]
    add("S2", "标签前缀段", "FAIL" if lab else "PASS", "; ".join(lab[:5]))

    # ---- 内部痕迹（编号/CSV/转义）----
    traces = [f"[{i}]{str(seq[i][1])[:35]}" for i, (k, t, p) in enumerate(seq)
              if k == "P" and re.search(r"[（(][SCRPD]\d{3}|_\.csv|\\-|\\\.|（推测）$", str(t))]
    add("S3", "内部痕迹", "FAIL" if traces else "PASS", "; ".join(traces[:5]))

    # ---- 9. 引用 ----
    body_txt = "".join(body_texts)
    # 正文段数（排除封面/来源注/图题表题）
    n_body = sum(1 for i, (k, t, p) in enumerate(seq)
                 if k == "P" and str(t) and not str(t).startswith("数据来源")
                 and not re.match(r"^[图表]\d", str(t))
                 and str(t) not in ("研究院  |  MARKET & PRODUCT INTELLIGENCE",)
                 and not re.match(r"^(日本户用储能市场深度调研报告|政策 · 市场)", str(t)))
    dup_char = re.findall(r"（见图图|（见表表", body_txt)
    miss_f = []
    miss_t = []
    for k, t, p in seq:
        if k == "FIGCAP":
            m = re.match(r"^图(\d+-\d+)", str(t))
            if m and ("（见图" + m.group(1) + "）") not in body_txt:
                miss_f.append("图" + m.group(1))
        if k == "TBLCAP":
            m = re.match(r"^表(\d+-\d+)", str(t))
            if m and ("（见表" + m.group(1) + "）") not in body_txt:
                miss_t.append("表" + m.group(1))
    detail9 = ""
    if dup_char:
        detail9 += "重复字:" + ",".join(dup_char) + " "
    if n_body == 0:
        # 骨架阶段（正文未 fill）：引用缺失是预期的，降级为 WARN，不阻断
        detail9 += f"(骨架阶段，正文 {n_body} 段，引用待 fill 后复查)"
        add(9, "引用完整性", "WARN", detail9)
    else:
        if miss_f:
            detail9 += "缺图引用:" + ",".join(miss_f[:8]) + " "
        if miss_t:
            detail9 += "缺表引用:" + ",".join(miss_t[:8])
        add(9, "引用完整性", "FAIL" if (dup_char or miss_f or miss_t) else "PASS", detail9)

    # ---- 10. 表头/表题证据字样 ----
    evi = []
    for tbl in doc.tables:
        for cell in tbl.rows[0].cells:
            if "证据" in cell.text:
                evi.append(cell.text.strip()[:15])
    for p in doc.paragraphs:
        if re.match(r"^表\d+-\d+", p.text.strip()) and "证据" in p.text:
            evi.append(p.text.strip()[:15])
    add(10, "表头/表题'证据'", "FAIL" if evi else "PASS", "; ".join(evi[:5]))

    # ---- 10B. 一表一题：表题必须紧邻且编号唯一 ----
    table_caption_issues = []
    caption_numbers = []
    for i, (kind, text, item) in enumerate(seq):
        if kind == "TBLCAP":
            match = re.match(r"^表\d+-\d+", str(text))
            if match:
                caption_numbers.append(match.group(0))
            if i + 1 >= len(seq) or seq[i + 1][0] != "TBL":
                table_caption_issues.append(f"[{i}]表题后不是表格")
    duplicate_numbers = sorted({number for number in caption_numbers if caption_numbers.count(number) > 1})
    if duplicate_numbers:
        table_caption_issues.append("重复编号:" + ",".join(duplicate_numbers))
    add("10B", "一表一题与编号唯一", "FAIL" if table_caption_issues else "PASS", "; ".join(table_caption_issues[:8]))

    # ---- 每章图表覆盖 ----
    from collections import OrderedDict
    ch = None
    stats = OrderedDict()
    for k, t, p in seq:
        s = str(t)
        if k == "H1":
            ch = s
            stats.setdefault(ch, [0, 0])
        elif k == "FIGCAP":
            stats.setdefault(ch, [0, 0])[0] += 1
        elif k == "TBLCAP":
            stats.setdefault(ch, [0, 0])[1] += 1
    no_fig = [c[:20] for c, (f, tb) in stats.items() if f == 0]
    no_tbl = [c[:20] for c, (f, tb) in stats.items() if tb == 0]
    detail = ""
    if no_fig:
        detail += "缺图章:" + ",".join(no_fig) + " "
    if no_tbl:
        detail += "缺表题章:" + ",".join(no_tbl)
    add("S4", "每章图表覆盖", "FAIL" if (no_fig or no_tbl) else "PASS", detail)

    # ---- 11. 空表检查（机械门禁 2026-08-07）----
    empty_tables = []
    for ti, tbl in enumerate(doc.tables, start=1):
        data_rows = tbl.rows[1:]
        if not data_rows:
            empty_tables.append(f"表{ti}(无数据行)")
            continue
        if all(not any(c.text.strip() for c in r.cells) for r in data_rows):
            empty_tables.append(f"表{ti}(数据行全空)")
    add("11", "空表检查", "FAIL" if empty_tables else "PASS", "; ".join(empty_tables[:8]))

    # ---- 重复章节标题 ----
    h1_seen = {}
    dup_h1 = []
    for k, t, p in seq:
        if k == "H1":
            s = str(t)
            num = re.match(r"^[一二三四五六七八九十]+、", s)
            key = num.group(0) if num else s[:6]
            h1_seen.setdefault(key, []).append(s)
    for key, v in h1_seen.items():
        if len(v) > 1:
            dup_h1.append(key)
    add("S5", "重复章节", "FAIL" if dup_h1 else "PASS", "; ".join(dup_h1))

    # ---- 输出 ----
    lines = [f"# Word IB 风格验证报告 — {args.docx}", ""]
    n_fail = 0
    n_warn = 0
    for cid, name, status, detail in results:
        if status == "PASS":
            mark = "✅"
        elif status == "WARN":
            mark = "⚠️"
            n_warn += 1
        else:
            mark = "❌"
            n_fail += 1
        lines.append(f"- {mark} **[{cid}] {name}**: {status}" + (f" — {detail}" if detail else ""))
    lines.append("")
    if n_fail == 0:
        lines.append(f"**结论: 全部通过 ✅**" + (f"（{n_warn} 项警告 ⚠️）" if n_warn else ""))
    else:
        lines.append(f"**结论: {n_fail} 项失败 ❌**" + (f"（{n_warn} 项警告 ⚠️）" if n_warn else ""))
    report = "\n".join(lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print("报告已写入:", args.out)
    print(report)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
