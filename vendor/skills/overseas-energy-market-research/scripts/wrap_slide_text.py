# -*- coding: utf-8 -*-
"""Auto-wrap overflowing slide text into multiple independent <text> lines.

Detects single-line <text> elements whose estimated width exceeds either
the canvas (1280) or the card right edge they start inside, and re-emits
them as multiple <text> elements with incremented y (same attributes).
NOTE: svg_to_pptx does not support <tspan>, so each line is its own <text>.

Rules:
- Only wraps body text (font-size >= 10), keeps titles/KPI numbers single-line.
- KPI numbers / serif display text (Georgia or font-size >= 25) are NEVER split —
  they must be pre-fit at authoring time (shorten wording / shrink font instead).
- Wraps at Chinese punctuation (，；。：、）) or space boundaries; falls back
  to character slicing.
- Skips text with text-anchor="end" (page numbers) — they right-align by
  design and are not card-bound.
"""
import glob

from _common import find_presentation_project, presentation_project_hint
import os
import re
import sys
from pathlib import Path

OUT = None  # resolved from --project-dir in main()


def card_rights(svg: str) -> list[tuple[float, float, float, float]]:
    """Return (x0, y0, x1, bottom) for large cards (height > 30).

    Handles both `<rect>` cards and the rounded-rectangle `<path d="M x0,y0 H x1 ...">`
    form produced by finalize_svg. For path cards the FULL d attribute is parsed:
    x0/y0 from M, x1 from the first H, y1 from the first V command (finalize emits
    `M x0,y0 H x1 A r,r ... V y1 A ... V y0 ...`). Decorative hairline dividers
    (h <= 30) and vertical accent bars (w <= 20) are excluded by the size filters —
    a wrong y0+60 height fallback used to resurrect them as phantom cards.
    """
    cards = []
    for m in re.finditer(
        r'<rect[^>]*x="([\d.]+)"[^>]*y="([\d.]+)"[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"',
        svg,
    ):
        x, y, w, h = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        if h > 30 and w > 20:
            cards.append((x, y, x + w, y + h))
    for m in re.finditer(r'<path[^>]*d="([^"]+)"', svg):
        d = m.group(1)
        mm = re.match(r'\s*M\s*([\d.]+)\s*,\s*([\d.]+)\s*H\s*([\d.]+)', d)
        if not mm:
            continue
        x0, y0, x1 = float(mm.group(1)), float(mm.group(2)), float(mm.group(3))
        vm = re.search(r'V\s*([\d.]+)', d)
        h = (float(vm.group(1)) - y0) if vm else 60
        w = x1 - x0
        if h > 30 and w > 20:
            # real bottom edge when known, else a generous window (y0+300)
            cards.append((x0, y0, x1, (y0 + h) if vm else y0 + 300))
    return cards


def text_width(text: str, font_size: float, serif: bool = False) -> float:
    """Rough width: CJK chars ~1.0em, latin/digits ~0.55em (serif ~0.62em —
    Georgia digits/M/W run wider than sans), space ~0.3em."""
    latin = 0.62 if serif else 0.55
    w = 0.0
    for ch in text:
        if ord(ch) > 0x2E80:  # CJK
            w += 1.0
        elif ch == " ":
            w += 0.32
        else:
            w += latin
    return w * font_size


def _tok_width(tok: str, font_size: float) -> float:
    """Width of an atomic token (same per-char model as text_width)."""
    return text_width(tok, font_size)


# CJK closing punctuation: a line must never START with these.
_CLOSING_PUNC = set('，。；：、）】》！？…')


def _tokenize(text: str) -> list[str]:
    """Split into atomic tokens that must stay on one line.

    - Numeric runs absorb a trailing unit ("351.6 MWh", "891 MWh") so a
      figure can never be split mid-number by a line break.
    - Latin words stay intact ("RENOINN", "GWh").
    - CJK chars are one token each (Chinese wraps anywhere).
    - Spaces and single punctuation chars are their own tokens.
    """
    toks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isdigit() or ch in '.–—':
            m = re.match(r'\d[\d.,–—]*(?:\s*[A-Za-z%€/]+)?', text[i:])
            if not m:
                # standalone dash/dot (e.g. the "–" in "低–高情景")
                toks.append(ch)
                i += 1
                continue
            toks.append(m.group(0))
            i += m.end()
        elif ch.isalpha() and ord(ch) < 0x2E80:
            m = re.match(r'[A-Za-z][A-Za-z0-9%€.,–—/+]*', text[i:])
            toks.append(m.group(0))
            i += m.end()
        elif ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            toks.append(text[i:j])
            i = j
        else:
            toks.append(ch)
            i += 1
    return toks


def wrap_text(text: str, max_w: float, font_size: float) -> list[str]:
    """Greedy wrap at atomic-token boundaries.

    Latin words and numeric runs (with trailing units) are kept intact, so
    "351.6 MWh" or "2026–2030" can never be split mid-number/mid-word.
    CJK characters pack one per token (Chinese wraps anywhere). Closing
    punctuation is attached to the current line to avoid orphaned "）" line
    starts. Oversized single tokens fall back to character slicing.
    """
    lines: list[str] = []
    cur = ''
    cur_w = 0.0
    for tok in _tokenize(text):
        tw = _tok_width(tok, font_size)
        if tok.isspace():
            # keep a space only if it fits; drop line-end spaces
            if cur and cur_w + tw <= max_w:
                cur += tok
                cur_w += tw
            continue
        if cur and cur_w + tw > max_w:
            if tok in _CLOSING_PUNC and cur_w + tw <= max_w + font_size * 0.5:
                cur += tok
                cur_w += tw
                continue
            lines.append(cur)
            cur = ''
            cur_w = 0.0
        if not cur and tw > max_w:
            # single token wider than the whole line: hard-slice char-wise
            buf = ''
            for ch in tok:
                cw = font_size * (1.0 if ord(ch) > 0x2E80 else (0.32 if ch == ' ' else 0.55))
                if buf and _tok_width(buf + ch, font_size) > max_w:
                    lines.append(buf)
                    buf = ch
                else:
                    buf += ch
            cur, cur_w = buf, _tok_width(buf, font_size)
            continue
        cur += tok
        cur_w += tw
    if cur:
        lines.append(cur)
    return lines


def process(svg: str) -> tuple[str, int]:
    cards = card_rights(svg)
    fixed = 0

    fixed_holder = {"n": 0}

    def _rewrap_tspans(open_tag, body, cards, holder):
        """Re-wrap an already-multiline text when one of its lines still
        exceeds the card width (e.g. after a width-budget change)."""
        xm = re.search(r'x="([\d.]+)"', open_tag)
        ym = re.search(r'y="([\d.]+)"', open_tag)
        fm = re.search(r'font-size="([\d.]+)"', open_tag)
        if not (xm and ym and fm):
            return body
        x, y, fs = float(xm.group(1)), float(ym.group(1)), float(fm.group(1))
        if fs >= 25 or 'Georgia' in open_tag:
            return body
        right = min(
            (cx1 for cx0, cy0, cx1, bottom in cards
             if cx0 - 5 <= x <= cx1 + 5 and cy0 - 5 <= y <= bottom + 10),
            default=1280.0,
        )
        max_w = (right - x - 4) * 0.90
        if max_w <= 10:
            return body
        # collect all line texts
        lines = re.findall(r'<tspan[^>]*>([^<]+)</tspan>', body)
        if not lines:
            return body
        # re-wrap the concatenated content is wrong (line breaks are semantic);
        # instead: for each line, if too wide, split it further
        new_lines = []
        changed = False
        for ln in lines:
            if text_width(ln, fs) <= max_w + 2:
                new_lines.append(ln)
                continue
            subs = wrap_text(ln, max_w, fs)
            new_lines.extend(subs)
            changed = True
        if not changed:
            return body
        holder["n"] += 1
        line_h = fs * 1.45
        parts = []
        for i, ln in enumerate(new_lines):
            yy = y + i * line_h
            tag = re.sub(r'y="[\d.]+"', 'y="%s"' % yy, open_tag, count=1)
            parts.append('<text%s>%s</text>' % (tag, ln))
        return "".join(parts)

    def replace_text(match):
        nonlocal fixed
        full = match.group(0)
        open_tag = match.group(1)  # attributes inside <text ...>
        body = match.group(2)
        # skip anchored page numbers
        if 'text-anchor="end"' in open_tag:
            return full
        # handle already-wrapped texts: re-wrap any tspan line that is still too wide
        if "<tspan" in body:
            return _rewrap_tspans(open_tag, body, cards, fixed_holder)
        xm = re.search(r'x="([\d.]+)"', open_tag)
        ym = re.search(r'y="([\d.]+)"', open_tag)
        fm = re.search(r'font-size="([\d.]+)"', open_tag)
        if not (xm and ym and fm):
            return full
        x, y, fs = float(xm.group(1)), float(ym.group(1)), float(fm.group(1))
        if fs < 10:
            return full
        # KPI numbers / serif display text must stay single-line (never split
        # a figure into two lines); shrink the wording instead.
        if fs >= 25 or 'Georgia' in open_tag:
            return full
        right = min(
            (cx1 for cx0, cy0, cx1, bottom in cards
             if cx0 - 5 <= x <= cx1 + 5 and cy0 - 5 <= y <= bottom + 10),
            default=1280.0,
        )
        max_w = (right - x - 4) * 0.90  # 10% safety margin for renderer width drift
        if max_w <= 10:
            return full
        if text_width(body, fs) <= max_w + 2:
            return full
        lines = wrap_text(body, max_w, fs)
        if len(lines) <= 1:
            return full
        fixed_holder["n"] += 1
        # keep the original opening tag attributes (font-family, fill, weight...)
        # but normalize x / y / font-size to floats
        new_open = open_tag
        new_open = re.sub(r'x="[\d.]+"', 'x="%s"' % x, new_open, count=1)
        new_open = re.sub(r'y="[\d.]+"', 'y="%s"' % y, new_open, count=1)
        new_open = re.sub(r'font-size="[\d.]+"', 'font-size="%s"' % fs, new_open, count=1)
        line_h = fs * 1.45
        # svg_to_pptx does not support <tspan>; emit each line as an independent
        # <text> element with incremented y (same attributes, y updated).
        parts = []
        for i, ln in enumerate(lines):
            yy = y + i * line_h
            tag = re.sub(r'y="[\d.]+"', 'y="%s"' % yy, new_open, count=1)
            parts.append('<text%s>%s</text>' % (tag, ln))
        return "".join(parts)

    pattern = re.compile(
        r'<text([^>]*)>(.*?)</text>',
        re.S,
    )
    new_svg = pattern.sub(replace_text, svg)
    return new_svg, fixed_holder["n"]


def check_only(svg: str) -> list[str]:
    """Return overflow descriptions without modifying the SVG (pre-flight check)."""
    cards = card_rights(svg)
    issues = []
    for m in re.finditer(r'<text([^>]*)>(.*?)</text>', svg, re.S):
        tag = m.group(1)
        body = m.group(2)
        if 'text-anchor="end"' in tag or '<tspan' in body:
            continue
        xm = re.search(r'x="([\d.]+)"', tag)
        ym = re.search(r'y="([\d.]+)"', tag)
        fm = re.search(r'font-size="([\d.]+)"', tag)
        if not (xm and ym and fm):
            continue
        x, y, fs = float(xm.group(1)), float(ym.group(1)), float(fm.group(1))
        if fs < 10:
            continue
        fam = re.search(r'font-family="([^"]*)"', tag)
        serif = bool(fam and ('georgia' in fam.group(1).lower()
                              or 'serif' in fam.group(1).lower()))
        right = min(
            (cx1 for cx0, cy0, cx1, bottom in cards
             if cx0 - 5 <= x <= cx1 + 5 and cy0 - 5 <= y <= bottom + 10),
            default=1280.0,
        )
        w = text_width(body, fs, serif)
        if right == 1280.0:
            # free-standing text (titles, section labels, cover lines): the
            # boundary is the canvas edge itself — must not leave the slide.
            if x + w > 1284:
                issues.append("x=%s y=%s 超出画布右界 1280（宽 %.0f/右界 %.0f）: %s" % (
                    x, y, w, x + w, body[:30]))
            continue
        if w > (right - x - 2) * 1.10:
            issues.append("x=%s y=%s 超出卡片右界 %.0f（宽 %.0f/可用 %.0f）: %s" % (
                x, y, right, w, right - x - 2, body[:30]))
    return issues


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Auto-wrap overflowing slide text into <tspan> lines.")
    parser.add_argument("--project-dir", default=".", help="Research project directory")
    parser.add_argument("--presentation-project", default=None,
                        help="High-fidelity presentation directory (auto-detected when omitted).")
    parser.add_argument("--check", action="store_true",
                        help="Pre-flight check only: report overflows without modifying files; exit 1 if any")
    args = parser.parse_args()
    project_root = Path(args.project_dir).expanduser().resolve()
    presentation = None
    if args.presentation_project:
        presentation = Path(args.presentation_project).expanduser().resolve()
        if not presentation.is_absolute():
            presentation = project_root / presentation
    else:
        presentation = find_presentation_project(project_root)
    if presentation is None:
        print("ERROR: presentation project directory not found;", presentation_project_hint(project_root))
        return 2
    out_dir = presentation / "svg_output"
    if not out_dir.exists():
        print("ERROR: svg_output not found:", out_dir)
        return 2
    total = 0
    all_issues = []
    for f in sorted(glob.glob(str(out_dir / "slide_*.svg"))):
        svg = Path(f).read_text(encoding="utf-8")
        if args.check:
            issues = check_only(svg)
            if issues:
                all_issues.append((os.path.basename(f), issues))
            continue
        new_svg, n = process(svg)
        if n:
            Path(f).write_text(new_svg, encoding="utf-8")
            print("%s: 换行 %d 处" % (os.path.basename(f), n))
            total += n
    if args.check:
        if all_issues:
            for name, issues in all_issues:
                print("溢出 %s: %d 处" % (name, len(issues)))
                for it in issues[:5]:
                    print("   ", it)
            print("校验失败：存在文本溢出（应先在写入时按卡片宽度预换行）")
            return 1
        print("校验通过：无文本溢出")
        return 0
    print("总计换行修复:", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())