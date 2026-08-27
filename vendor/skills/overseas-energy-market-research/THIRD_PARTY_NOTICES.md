# Third-Party Notices

本仓库（overseas-energy-market-research）以 Apache License 2.0 发布（见 `LICENSE`）。
以下内嵌组件来自第三方项目，各自保留其原始许可证与版权声明。
本文件不授予这些第三方组件的额外权利；各组件按各自许可条款使用。

| 组件 | 位置 | 许可 | 版权 |
|---|---|---|---|
| AnySearch CLI（官方 3.0.1 零 diff 内嵌） | `scripts/anysearch/` | Apache 2.0（见该组件 `NOTICE` 与官方 LICENSE 声明） | Copyright 2026 AnySearch |
| kami 文档模板（投行风格 Word 模板来源） | `assets/templates/word/` 及融合模板 | MIT | Copyright (c) 2026 Tw93 |
| 数学建模链指令文档（24 个 skill，零 diff 内嵌） | `references/modeling_chain/` | MIT（各文件 YAML frontmatter 保留 `license: MIT`） | 各原作者 |
| PPT Master 迁移资产（119 脚本 + 模板/图标/版式/品牌库） | `scripts/`（project_manager.py 等）、`templates/` | 来源未声明许可；本仓库按 Apache 2.0 再分发，来源注明为原 ppt-master skill | 原 ppt-master 作者 |
| Kimi WebBridge 客户端与官方契约文档 | `scripts/_kimi_webbridge.py`、`references/kimi-webbridge-*.md` | 本仓库原创（客户端实现）；官方契约文档按其原始用途内嵌 | 本仓库 / Kimi WebBridge |
| 其余脚本（web_collection 包、全部验证器、回归测试、安装脚本） | `scripts/` | 本仓库原创，Apache 2.0 | 本仓库 |

## 注意

- 分发或修改本仓库时，须保留本文件与各内嵌组件自身的许可/版权声明
  （如 `scripts/anysearch/README_embedded.md` 中的 Apache 2.0 声明、建模链各文档 frontmatter 的 `license: MIT`）。
- 本仓库不含任何闭源或传染性许可组件。
