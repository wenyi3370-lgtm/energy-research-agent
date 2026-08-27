# Kimi WebBridge 客户端契约（官方 SKILL.md 完整内嵌）

> 来源：官方 `kimi-webbridge` skill `SKILL.md`（工具契约逐段内嵌，未删减功能）。
> 本 Skill 通过 `scripts/_kimi_webbridge.py` 的 `command(action, args, session)` 直连
> 本地 daemon `http://127.0.0.1:10086/command`（POST JSON，payload 与官方 curl 示例逐字段一致），
> 也可按下方契约直接 curl。运行时依赖：daemon 二进制 + 浏览器扩展（外部组件，见
> `references/kimi-webbridge-operations.md`）。

## Health check (always do this first)

```bash
~/.kimi-webbridge/bin/kimi-webbridge status
```

- `running: true` and `extension_connected: true` — healthy. Proceed.
- Anything else — read `references/kimi-webbridge-operations.md`（安装/启动/诊断路由表）。

## Tools

| Tool | Args | Returns | Note |
|------|------|---------|------|
| `navigate` | `url`, `newTab`(bool), `group_title` | `{success, url, tabId}` | First call opens a tab. `group_title` sets the group's visible label |
| `find_tab` | `url`, `active`(bool) | `{success, url, tabId}` | Select an already-open tab as the current one |
| `snapshot` | — | `{url, title, tree}` with `@e` refs | **Accessibility tree** (text) — use this to read page content and locate elements |
| `click` | `selector` (@e ref or CSS) | `{success, tag, text}` | Synthetic `el.click()` |
| `fill` | `selector`, `value` | `{success, tag, mode}` | Works on `<input>`/`<textarea>` AND `[contenteditable]`. `mode` is `"value"` or `"contenteditable"` |
| `evaluate` | `code` (supports async/await) | `{type, value}` | |
| `screenshot` | `format`(png\|jpeg), `quality`(0-100), optional `selector` (@e/CSS), optional `path` | `{format, path, sizeBytes, mimeType}` | Returns a file path, not base64 |
| `network` | `cmd`(start\|stop\|list\|detail), `filter`, `requestId` | request/response data | |
| `upload` | `selector`, `files`(string[]) | `{success, fileCount}` | |
| `save_as_pdf` | `paper_format`, `landscape`, `scale`, `print_background`, optional `path` | `{path, sizeBytes, mimeType, pageTitle}` | Render current page → PDF, returns a file path |
| `list_tabs` | — | `{success, tabs:[{tabId, url, title, active, groupTitle}]}` | Inspect tabs in the current session |
| `close_tab` | — | `{success, closed: bool}` | Close the current tab in the session |
| `close_session` | — | `{success, closed: int}` | Close all tabs in the session — `closed` is the count |

## Call Format

Every command carries a top-level `session` naming the current task:

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"navigate","args":{"url":"https://example.com","newTab":true,"group_title":"My task"},"session":"my-task"}'
```

内嵌等价调用：

```python
from _kimi_webbridge import command
command("navigate", {"url": "https://example.com", "newTab": True, "group_title": "My task"}, "my-task")
```

## Sessions

**One task = one session = one tab group.**

1. Pick one session name when the task starts, put it on **every** command, and never change it mid-task.
2. One task uses one session — even across multiple sites.
3. Name the session after the **task**, not the site or domain.
4. `group_title` is the human-readable label shown on the group in the browser, written in the user's language (match the conversation — Chinese or English). Pass it on the **first** `navigate`.
5. Use multiple sessions only when the user asks for several unrelated tasks at once.

When the task is finished and the user no longer needs these pages, `close_session` clears the whole group. If they might want to look further, deliver the answer first and leave the tabs open.

## Tabs and the current tab

Single-tab tools (`snapshot`, `click`, `fill`, `screenshot`, `save_as_pdf`) act on the **current tab** — the one you most recently opened with `navigate` or selected with `find_tab`.

- **Opening pages**: use `newTab:true` when pages should coexist (comparing, cross-referencing); omit it to send the current tab to a new URL.
- **Going back to an earlier tab**: call `find_tab` with the tab's **full URL** (from `list_tabs` or the earlier `navigate` result). A bare root domain may miss a `www.` tab, so prefer the exact URL. `active:true` picks the tab the user is currently viewing; otherwise the leftmost match wins.
- If `find_tab` returns "no open tab found", the page isn't open — `navigate` with `newTab:true` instead.

## Screenshots

The daemon writes the image to disk and returns `{format, path, sizeBytes, mimeType}` — never base64. Take the `.path` and open it with the `Read` tool to actually see it.

- Default: PNG of the visible viewport, daemon picks a temp path.
- Options: JPEG quality, element-only via `@e`/CSS selector, custom output path.
- A caller-supplied `path` is honored verbatim (parent dirs created, existing file overwritten) — use a unique name to avoid clobbering. `save_as_pdf` follows the same rule.

## Prefer snapshot over CSS/JS selectors

`snapshot` returns interactive elements with `@e` refs based on semantic role/name. Use them directly with click/fill — they survive CSS class hash changes that break manually-written selectors.

Fall back to `evaluate` (JS) only when:
- The target has no `@e` ref in the snapshot
- You need attributes not in the snapshot (e.g., `href`)
- You need to dispatch complex event sequences, or scroll

## Evaluate Tips

- Always use compact `JSON.stringify(data)` — never add `null, 2` formatting.
- `evaluate` calls share the page's JS realm — re-declaring the same `const`/`let` across two calls throws `SyntaxError`. Wrap in an IIFE for a fresh scope: `(() => { const x = ...; return x; })()`.

## Text input — use `fill`

`fill` handles all three text input shapes. Pass selector (CSS or `@e` ref) + value:

| Target | What `fill` does | Returned `mode` |
|--------|------|------|
| `<input>` / `<textarea>` | Sets `.value` via native setter, fires `input`/`change`. | `"value"` |
| `[contenteditable]` (ProseMirror / TipTap / Lexical / Slate / Quill etc.) | Focuses, selects all existing content, calls `document.execCommand('insertText', ...)` which fires `beforeinput`/`input` with `inputType:'insertText'` and `data:value`. | `"contenteditable"` |
| Other element | Best-effort `.value` + events. | `"value"` |

`fill` is **clear-and-insert**: existing content is replaced. For "append to existing text", read the current value via `evaluate`, concatenate, then `fill` with the result.

## Form submit / special keys

There's no separate "press Enter" tool. To submit a form, click the submit button directly. To dispatch a key event programmatically (e.g. Escape to close a modal):

```bash
{"action":"evaluate","args":{"code":"document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"}}
```

## Save the current page as PDF

`save_as_pdf` renders the current page to PDF and returns the file path. All args optional:
- `paper_format`: `letter` (default) \| `a4` \| `legal` \| `a3` \| `tabloid`
- `landscape`: `false` (default)
- `scale`: `1.0` (default), range `[0.1, 2.0]`
- `print_background`: `true` (default) — keep background colors
- `path`: caller-supplied output path; if absent, daemon picks a default under OS temp dir using the page title as the filename

`path` semantics match `screenshot`: written verbatim, parent dirs auto-created, existing files overwritten.

Decoded PDF cap is 100 MB. Above that the daemon refuses; reduce `scale` or split the page.

## Known limitations

- **Sites that strictly check `event.isTrusted`** (some banking portals, captcha challenges) reject `fill` and `click` because both go through DOM-level synthetic events (`isTrusted=false`). This is a product boundary, not a bug.
- **Cross-origin iframes**: `fill`, `click`, `evaluate`, and `snapshot` operate on the top frame. If a target element lives in a same-page iframe from a different origin, navigate to the iframe's URL directly instead.

## Versions

Daemon, extension, and this skill share a 1:1 version string. Read both via:

```bash
~/.kimi-webbridge/bin/kimi-webbridge status
# {"version":"<daemon>", "extension_version":"<extension>"}
```

If a tool returns an error containing **"Please update the Kimi WebBridge extension"**, the user's extension is older than this skill. Tell the user:

> 请更新 Kimi WebBridge 浏览器扩展后重试：https://kimi.com/features/webbridge

Don't retry the failed tool. Don't auto-switch skill versions based on `extension_version` — the pairing protocol isn't finalized.

## 内嵌客户端（scripts/_kimi_webbridge.py）

- `command(action, args, session, timeout=60)` — 上述全部 action 的直连入口（payload 与 curl 示例逐字段一致）；
- `ensure_ready(binary=None, auto_start=True)` — 健康检查硬门禁（daemon running + extension_connected）；
- `ACTION_CONTRACT` — 13 个 action 的只读契约表（必填/可选参数、返回字段）；
- `validate_action_args(action, args)` — 按契约表机械校验必填参数；
- `classify_failure(result, status)` — 失败归一分类（version_mismatch / extension_disconnected /
  timeout / access_authentication / challenge / empty_snapshot / wrong_current_tab /
  synthetic_event_limitation / daemon_stopped / not_installed）；
- `normalize_session(session)` — 任务级 session 名称规范；
- `daemon_start / daemon_stop / daemon_restart / daemon_logs` — 生命周期透传。

**硬性规则**：插件未连接或 daemon 未运行时，必须显式记录 `bridge_unavailable` 并提示用户
（打开浏览器/启用扩展/安装 daemon），**不得假装采集完成**。
