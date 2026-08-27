# 海外能源市场调研 Skill（overseas-energy-market-research）

一体化的海外能源市场调研 AI Skill：联网证据采集、数学建模、投行/咨询风格的
Word + Excel + 高保真 PPT 交付，全阶段机械门禁。**单份 Skill 自包含，不依赖任何外部 Skill 安装。**

英文说明：[README.md](README.md)

## 能力一览

| 能力 | 状态 | 说明 |
|---|---|---|
| 联网采集（搜索 + 浏览器） | 内嵌 | 官方 AnySearch 3.0.1 CLI 零 diff 内嵌（`scripts/anysearch/`）；Kimi WebBridge 客户端与契约文档内嵌（`scripts/_kimi_webbridge.py`、`references/kimi-webbridge-*.md`） |
| 采集完整性门禁 | 内嵌 | 采集台账（`13_Collection_Attempt_Journal.csv`）、防少搜、防假完成、R1/R2/R3 饱和数量下限、来源台账、记录注册表 |
| 数学建模完整链 | 内嵌 | 24 个建模指令文档零 diff 内嵌（`references/modeling_chain/`，MIT）；G1–G6 机械门（`scripts/validate_modeling_chain_gates.py`），含 AI 不可自置通过的人工决策门 |
| Word 生产 | 内嵌 | 投行风格模板、三线表、内嵌图表、正文 ≥15,000 字符、逐页渲染 QA |
| Excel 生产 | 内嵌 | 咨询浅色 + jade 主题、公式保留、重算、打印布局 QA |
| 图表生产 | 内嵌 | Python SVG 主文件 + 300dpi PNG、来源/哈希登记、结论优先契约 |
| 高保真 PPT | 内嵌 | 完整 ppt-master 管线：design_spec → 手写 SVG → DrawingML 导出，转场/动画/讲稿，LibreOffice+PyMuPDF 逐页 QA，EWO 生图回退 |
| Stage 0–8 门禁 | 内嵌 | `scripts/validate_stage_gate.py` + `scripts/run_workflow.py` 编排 |

**运行时前提**（非 Skill 安装）：Python 3.10+ 与 `requirements.txt`、LibreOffice（Office 渲染）、
AnySearch API key（可选，匿名可用但限流较低）、Kimi WebBridge daemon + 浏览器插件（浏览器采集）、
EWO 生图 API（可选，封面插图）。

## 安装

```bash
# 1. 把本 Skill 复制到 AI 客户端的 skills 目录
cp -r overseas-energy-market-research ~/.claude/skills/

# 2. 安装 Python 依赖（使用 Python 3.10+）
pip install -r requirements.txt

# 3. 自检
python scripts/verify_install.py
```

Windows 用户可运行 `scripts/install.ps1`（带备份的复制 + 依赖 + 自检）；macOS/Linux 用 `scripts/install.sh`。

随后配置（见 `.env.example`）：
- `ANYSEARCH_API_KEY` — 可选，提高搜索限流额度
- `EWO_ORIGIN` / `EWO_KEY` — 可选，AI 封面生图
- LibreOffice — Word/Excel/PPT 渲染 QA 必需
- Kimi WebBridge daemon + 浏览器扩展 — 浏览器/登录采集必需

### LibreOffice 安装说明

- Windows：从 https://www.libreoffice.org/download/ 安装（默认路径 `C:\Program Files\LibreOffice\program\soffice.exe`）；
- macOS：`brew install --cask libreoffice`；
- Linux (Debian/Ubuntu)：`sudo apt install libreoffice`；
- 安装后运行 `python scripts/web_collection/cli.py doctor` 确认渲染依赖。

### EWO 生图配置

默认本地代理端点 `http://127.0.0.1:18799`，token 位于 `~/.ewo/.habitat-local-proxy-token`。
`EWO_ORIGIN` / `EWO_KEY` 指向即可；EWO 不可用时 PPT 封面自动降级为浅色咨询排版 + 手写 SVG。

## 快速开始

```bash
# 初始化研究项目（冻结数量政策快照 + 任务模板）
python scripts/run_workflow.py --init --project-dir ./my-project \
  --region Thailand --category "Residential Battery Energy Storage" \
  --market-model-pair "thailand::BYD Battery-Box Premium 8.3kWh"

# 环境体检（内嵌 CLI 与官方哈希、插件、依赖、台账）
python scripts/web_collection/cli.py doctor --project-dir ./my-project

# 真实采集（anysearch 搜索/提取、kimi 浏览器；台账自动记录）
python scripts/web_collection/cli.py search "Thailand BESS policy 2026" --task-id T1 --round 1 --round-goal coverage --project-dir ./my-project

# 采集后跑门禁
python scripts/validate_collection_tasks.py --project-dir ./my-project
python scripts/validate_collection_attempts.py --project-dir ./my-project
python scripts/validate_source_ledger.py --project-dir ./my-project
```

## 一键总流程（单入口）

```bash
# 全流程：init(缺省时) -> check(0-4) -> collect -> modeling -> 最终报告 -> 审计
python scripts/run_workflow.py --all --project-dir ./my-project \
  --region Thailand --category "Residential Battery Energy Storage" \
  --analysis-branch modeling

# 预览将执行的命令（不执行）
python scripts/run_workflow.py --all --dry-run --project-dir ./my-project --region Thailand --category BESS

# 仅机械采集（按任务表执行，自动写台账）
python scripts/run_workflow.py --collect --project-dir ./my-project

# 建模链脚本化步骤（门禁 + 人工门通过后生成 12/13/14）
python scripts/run_workflow.py --modeling --project-dir ./my-project
```

说明：建模链人工决策门（G2.5/G4.5，`decided_by=human`）AI 不可自置通过——`--modeling`
在门未决时报告待决状态，不会假装通过。

## 回归测试（全部离线，非 0 退出码即失败）

```bash
python scripts/regression_test_anysearch_embed.py   # anysearch 全命令面 + 错误归一化
python scripts/regression_test_kimi_embed.py        # kimi 客户端契约、信封格式、登录态
python scripts/regression_test_web_collection.py    # 端到端采集流程 + 完整性门禁
python scripts/regression_test_modeling_chain.py    # G1–G6 门禁、人工门防伪造（14 用例）
python scripts/regression_test_word_delivery.py     # Word 生产
python scripts/regression_test_excel_delivery.py    # Excel 生产
python scripts/regression_test_figure_delivery.py   # 图表生产
python scripts/regression_test_ppt_delivery.py --work-dir <tmp>  # PPT 生产
```

真实验收（真实 API 调用、真实浏览器）记录见 `assets/config/integration_manifest.yaml`。

## 许可证

Apache License 2.0。内嵌第三方组件保留各自许可——见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
