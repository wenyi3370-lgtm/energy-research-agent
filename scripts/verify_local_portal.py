"""Headless Playwright acceptance check for the local research portal."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="load the live portal and verify controls without creating a task",
    )
    args = parser.parse_args()

    console_errors: list[str] = []
    result: dict[str, object] = {"base_url": args.base_url}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_text("企业研究仅由本页按钮启动，不会定时自动运行").wait_for()
        if args.smoke_only:
            for selector in (
                "#prepareBtn",
                "#stopAllBtn",
                "#intelBtn",
                "#pauseBtn",
                "#resumeBtn",
            ):
                page.locator(selector).wait_for(state="attached")
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.screenshot), full_page=True)
            browser.close()
            if console_errors:
                raise AssertionError(f"browser console errors: {console_errors}")
            result.update(
                {
                    "portal_loaded": True,
                    "manual_controls_present": True,
                    "daily_push_controls_present": True,
                    "console_errors": console_errors,
                }
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0

        page.locator("#company").fill("网页功能验收测试企业")
        page.locator("#topics").fill("本地网页触发, 控制链路验收")
        page.locator("#prepareBtn").click()
        page.locator("#status").get_by_text("任务已准备", exact=False).wait_for()
        page.locator("#parsedCard").wait_for(state="visible")
        if page.locator("#startBtn").is_disabled():
            raise AssertionError("start button remained disabled after portal prepare")

        page.locator("#startBtn").click()
        page.locator("#runStatus").get_by_text("调查已开始", exact=False).wait_for()
        run_url = page.locator("#viewResult").get_attribute("href")
        if not run_url:
            raise AssertionError("result link was not populated")

        run_status = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = page.request.get(f"{args.base_url}{run_url}")
            if not response.ok:
                raise AssertionError(f"run status request failed: HTTP {response.status}")
            run_status = response.json().get("status")
            if run_status in {
                "PUBLISHED",
                "FAILED",
                "BLOCKED",
                "REVIEW_REQUIRED",
                "REJECTED",
            }:
                break
            time.sleep(0.25)
        if run_status not in {
            "PUBLISHED",
            "FAILED",
            "BLOCKED",
            "REVIEW_REQUIRED",
            "REJECTED",
        }:
            raise AssertionError(f"portal-started run did not finish: {run_status}")

        page.locator("#pauseBtn").click()
        page.locator("#intelStatus").get_by_text("推送已停止", exact=False).wait_for()
        paused = page.request.get(f"{args.base_url}/api/v1/intelligence/status").json()
        if paused != {"paused": True}:
            raise AssertionError(f"pause status mismatch: {paused}")
        page.locator("#resumeBtn").click()
        page.locator("#intelStatus").get_by_text("推送已恢复", exact=False).wait_for()
        resumed = page.request.get(f"{args.base_url}/api/v1/intelligence/status").json()
        if resumed != {"paused": False}:
            raise AssertionError(f"resume status mismatch: {resumed}")

        page.on("dialog", lambda dialog: dialog.accept())
        page.locator("#stopAllBtn").click()
        page.locator("#stopAllStatus").get_by_text("当前没有运行中的调查任务").wait_for()

        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.screenshot), full_page=True)
        browser.close()

    if console_errors:
        raise AssertionError(f"browser console errors: {console_errors}")
    result.update(
        {
            "portal_loaded": True,
            "manual_prepare_visible": True,
            "manual_start_effective": True,
            "run_status": run_status,
            "pause_resume_effective": True,
            "stop_all_effective": True,
            "console_errors": console_errors,
        }
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
