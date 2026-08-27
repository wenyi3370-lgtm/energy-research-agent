# Kimi WebBridge Operations（官方 operations.md 完整内嵌）

> 来源：官方 `kimi-webbridge` skill `references/operations.md`（逐段内嵌，未删减）。
> 本文档与 `references/kimi-webbridge-client-contract.md` 一起构成内嵌后的完整操作指引；
> daemon 二进制与浏览器扩展为运行时外部组件（同 LibreOffice 定位），安装/启动见下文。

Read this file when the health check in the client contract indicates the daemon is missing, not running, or the extension isn't connected — or when the user explicitly asks to install, start, stop, restart, or troubleshoot kimi-webbridge.

## Path convention

The `kimi-webbridge` binary always lives at `~/.kimi-webbridge/bin/kimi-webbridge`, regardless of how it was installed. Status, PID, and logs live under `~/.kimi-webbridge/`.

## Routing table (what to do based on status)

Run: `~/.kimi-webbridge/bin/kimi-webbridge status`

| Observed | Action |
|---|---|
| `command not found` or binary missing | Not installed. Run: `curl -fsSL https://cdn.kimi.com/webbridge/install.sh \| bash` |
| `{"running": false, ...}` | Daemon not running. Run: `~/.kimi-webbridge/bin/kimi-webbridge start` |
| `{"running": true, "extension_connected": false, ...}` | Extension not connected. Tell the user: "If you've already installed the Kimi WebBridge extension, please open your browser and try again. If not yet installed, see https://www.kimi.com/features/webbridge (中文: https://www.kimi.com/zh-cn/features/webbridge) for install instructions." |
| `{"running": true, "extension_connected": true, ...}` | Healthy. Proceed with tool calls. |

## /status JSON fields

- `running` (bool) — daemon listening on `:10086`
- `port` (int) — 10086
- `version` (string) — daemon build version
- `extension_connected` (bool) — a WebSocket client is attached
- `extension_id` (string) — the Chrome/Edge extension ID, empty if none
- `uptime_seconds` (int)

## Daily operations

- **Check status:** `~/.kimi-webbridge/bin/kimi-webbridge status`
- **Start:** `~/.kimi-webbridge/bin/kimi-webbridge start` (idempotent — safe to call when already running)
- **Stop:** `~/.kimi-webbridge/bin/kimi-webbridge stop`
- **Restart after unexpected state:** `~/.kimi-webbridge/bin/kimi-webbridge restart`
- **View recent logs:** `~/.kimi-webbridge/bin/kimi-webbridge logs -n 100`
- **Follow logs live:** `~/.kimi-webbridge/bin/kimi-webbridge logs -f`
- **View previous run's logs:** `~/.kimi-webbridge/bin/kimi-webbridge logs --prev`

内嵌等价调用（脚本封装）：`scripts/_kimi_webbridge.py` 的
`daemon_start / daemon_stop / daemon_restart / daemon_logs(lines=100, follow=False, previous=False)`
均为上述 CLI 子命令的透传，行为一致。

## Install flags (install.sh)

When running `install.sh`:

- Default: install binary + start daemon + install skills to all detected AI agents
- `--no-start`: install binary + skills, but don't start the daemon
- `--no-skill`: install binary + start daemon, but skip skill installation
- `-h` or `--help`: show usage

## Diagnosing common failures

| Symptom | Action |
|---|---|
| `start` fails with "address already in use" | `~/.kimi-webbridge/bin/kimi-webbridge stop && ~/.kimi-webbridge/bin/kimi-webbridge start`; if that fails, `lsof -i :10086` to find the conflicting process. |
| Tool calls time out | `~/.kimi-webbridge/bin/kimi-webbridge logs -n 100` — check for `[error]` / `panic` lines. |
| `extension_connected` stays `false` after install | Browser extension not running. If the user has it installed, ask them to open the browser and retry; otherwise direct them to https://www.kimi.com/features/webbridge (中文: https://www.kimi.com/zh-cn/features/webbridge). |
| `status` returns `extension_connected: true` but tool call fails | May be a multi-browser conflict. `~/.kimi-webbridge/bin/kimi-webbridge logs` will show recent upgrade rejections. |

## 与本 Skill 采集流程的衔接

- 采集前先跑 `scripts/web_collection/cli.py doctor`（会执行上述健康检查）；
- 插件未连接或 daemon 未运行时：**显式记录 `bridge_unavailable`，不得假装采集完成**，
  按上方路由表处理后再重试；
- 故障统一由 `scripts/_kimi_webbridge.py` 的 `classify_failure()` 分类
  （version_mismatch / extension_disconnected / timeout / access_authentication /
  challenge / empty_snapshot / wrong_current_tab / synthetic_event_limitation /
  daemon_stopped / not_installed）。
