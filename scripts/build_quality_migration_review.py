from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = Path.home() / "Desktop" / "企业调研Skill_v0.7.0质量门迁移验收.html"


def main() -> None:
    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>企业调研 Skill v0.7.0 质量门迁移验收</title><style>
:root{--ink:#21122b;--purple:#6f2b86;--lav:#d9ade8;--paper:#f6f3f7;--muted:#716979;--green:#0f766e;--red:#b42318}*{box-sizing:border-box}body{margin:0;font-family:"Microsoft YaHei",Arial,sans-serif;background:var(--paper);color:var(--ink)}header{padding:42px 7vw;background:linear-gradient(120deg,#21122b,#4b1f5c 64%,#6f2b86);color:white}header small{letter-spacing:.18em;color:#d9ade8}h1{font:700 clamp(28px,4vw,52px) Georgia,"Microsoft YaHei";margin:.35em 0}.sub{max-width:900px;line-height:1.8;color:#eee4f1}.wrap{max-width:1200px;margin:auto;padding:34px 24px 70px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.card{background:#fff;border:1px solid #e6dfea;border-radius:14px;padding:22px;box-shadow:0 8px 25px rgba(33,18,43,.06)}.kpi{font:700 34px Georgia;color:var(--purple)}.label{color:var(--muted);font-size:13px}.pass{color:var(--green)}.block{color:var(--red)}h2{margin-top:38px;font:700 24px Georgia,"Microsoft YaHei"}table{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}th,td{padding:14px;text-align:left;border-bottom:1px solid #eee7f0;vertical-align:top}th{background:#eee8f1;color:#4b1f5c}code{background:#f1edf3;padding:2px 6px;border-radius:5px}.bar{height:10px;background:#e7dfea;border-radius:99px;overflow:hidden;margin:8px 0 4px}.bar span{display:block;height:100%;background:var(--purple)}ul{line-height:1.8}@media(max-width:780px){.grid{grid-template-columns:1fr}}
</style></head><body><header><small>SEVC · EVIDENCE-FIRST RESEARCH</small><h1>质量门迁移验收 · v0.7.0</h1><p class="sub">已将 overseas-energy-market-research 的强制规则泛化迁入企业调研 Skill：三轮数据饱和、Word 正式篇幅与逐页渲染、PPT 高保真视觉注册。未复制国家/住宅储能/电商平台专属配额。</p></header><main class="wrap">
<section class="grid"><article class="card"><div class="kpi">42 / 42</div><div class="label">自动化回归测试通过</div></article><article class="card"><div class="kpi">3 Rounds</div><div class="label">R1 广度 · R2 深度 · R3 三角验证</div></article><article class="card"><div class="kpi">15k / 30p</div><div class="label">正式 Word 最低字符 / 渲染页</div></article></section>
<h2>迁移后的停止搜索判据</h2><table><tr><th>门</th><th>机械要求</th><th>未满足时</th></tr><tr><td>执行覆盖</td><td>每个 scope goal 都有 R1/R2/R3、attempt journal 与 raw capture</td><td class="block">PARTIAL / BLOCKED</td></tr><tr><td>边际新增</td><td>连续 2 批无高优新增，最近批次边际高优新增率 ≤5%</td><td class="block">继续定向搜索</td></tr><tr><td>证据独立</td><td>关键结论由权威 A 源或独立来源完成三角验证</td><td class="block">禁止标记完整</td></tr><tr><td>缺口闭合</td><td>零关键缺口、零未展开高优发现</td><td class="block">预算耗尽也不得称饱和</td></tr></table>
<h2>Word 正式交付门</h2><section class="grid"><article class="card"><b>内容深度</b><div class="bar"><span style="width:16.6%"></span></div><p>上一轮测试企业样稿：2,483 字 / 15,000 字最低线</p><p class="block">反向验收：BLOCKED</p></article><article class="card"><b>结构与密度</b><ul><li>13 个核心章节 + 4 个附录</li><li>每章 4–6 个实质分析段</li><li>标题后、图表前至少 50 字分析</li><li>每个核心章至少一个决策图表</li></ul></article><article class="card"><b>渲染验收</b><ul><li>同名 PDF 必须存在</li><li>默认至少 30 页</li><li>逐页检查 TOC、孤行表题、图题、附录</li><li>短报告须由用户明确要求</li></ul></article></section>
<h2>PPT 高保真门</h2><table><tr><th>维度</th><th>正式要求</th></tr><tr><td>叙事</td><td>storyline + evidence map + design_spec + spec_lock；正文动作标题</td></tr><tr><td>视觉</td><td>每页至少一个有效视觉，至少 4 类版式，不允许连续 3 页同版式</td></tr><tr><td>品牌</td><td>深海军紫科技封面；白底咨询正文；克制紫/钴蓝/冷灰；SEVC 公司识别</td></tr><tr><td>证据</td><td>每页来源、更新日期、偏差/假设；真实产品/工厂/图表优先</td></tr><tr><td>注册</td><td>全页渲染 + contact sheet + 全页目检 + 至少一次修复后全量重渲染 + quality.json</td></tr></table>
<h2>冲突处理</h2><ul><li>保留企业调研正常路径的自主执行，不增加常规大纲审批暂停。</li><li>人工批准仅用于范围/政策升级和数据缺口例外。</li><li>PPT Master 自身八项视觉确认继续保留。</li><li>联网仍只允许 AnySearch 与 Kimi WebBridge；没有引入 Web-Rooter、web-access 或其他搜索路径。</li></ul>
<p class="label">Skill path: C:\\Users\\Wenyi Zhang\\Desktop\\企业调研skill\\enterprise-energy-research · version 0.7.0</p></main></body></html>"""
    TARGET.write_text(html, encoding="utf-8")
    print(TARGET)


if __name__ == "__main__":
    main()
