# AnySearch CLI — 内嵌副本（官方 3.0.1 零改动搬运）

本目录是官方 `anysearch` skill（3.0.1）CLI 的**零改动拷贝**，用于让本 Skill
（overseas-energy-market-research）不依赖外部 anysearch skill 即可完成搜索、
垂直域检索、批量搜索与网页正文提取。功能与官方 CLI 完全一致：
`search / batch_search / extract / get_sub_domains / doc` 全部命令、全部参数、
16 个垂直域、批量 ≤5、max_results 钳制 10、PowerShell 引号剥离容错。

## 许可证声明（必须保留）

- 源码：`anysearch_cli.py`、`shared/constants.json`、`shared/doc_spec.md`
- 版权：AnySearch, Copyright 2026 AnySearch
- 许可证：Apache License, Version 2.0（完整文本见
  https://www.apache.org/licenses/LICENSE-2.0 ；本 skill 副本未包含 LICENSE 文件，
  分发/修改时须随附 Apache 2.0 许可文本与 NOTICE 声明）
- 本目录文件**禁止手工编辑**。官方更新后通过 doctor 的官方源哈希对比提示，
  再整体重新拷贝（保持零 diff）。

## API Key 配置（迁移说明）

官方 skill 的 .env 查找路径是 `anysearch/scripts/.env` 与 `anysearch/.env`；
内嵌后查找路径变为（与官方 `_load_env()` 逻辑一致，代码未改动）：

1. `scripts/anysearch/.env`（本目录下的 `.env`）
2. `scripts/anysearch/../.env`（即 `scripts/.env`）

优先级固定为：`--api_key` > `.env` 文件 > 环境变量 `ANYSEARCH_API_KEY` > 匿名。

将已有 key 迁移到上述任一位置即可（.env 格式：一行 `ANYSEARCH_API_KEY=sk-xxx`，
支持 BOM，utf-8-sig 读取）。也可直接设置环境变量 `ANYSEARCH_API_KEY`。

## 代理

与官方一致：requests 自动读取 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量。
Windows 本机惯例：`export HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897`
后再调用 CLI。

## 调用方式

```bash
CLI="python <skill_root>/scripts/anysearch/anysearch_cli.py"
$CLI search "Thailand BEV sales 2025" --max_results 5
$CLI get_sub_domains --domain energy
$CLI search "query" --domain energy --sub_domain energy.electricity --sdp location=Thailand,metric=price
$CLI batch_search --query "q1" --query "q2" --max_results 4
$CLI extract "https://example.com/page" > raw_capture/r2_egat.md
$CLI doc          # AI 接口规格（离线）
```

优先使用 `scripts/web_collection/cli.py`（统一入口，自动记录采集台账与原始捕获）；
本目录 CLI 亦可直接调用（同等记录义务：URL、访问日期、raw capture 必须入账）。

## 双路径（与外部官方 skill 的兼容）

若本机仍安装官方 `anysearch` skill，`web_collection/cli.py` 支持
`--official-cli <路径>` 显式走官方 CLI（行为与封装前逐字节一致）。
doctor 命令会对比官方源哈希，提示是否需要同步本内嵌副本。
