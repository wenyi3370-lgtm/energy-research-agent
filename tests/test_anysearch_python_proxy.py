from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import os


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "vendor" / "skills" / "anysearch" / "scripts" / "anysearch_cli.py"
EMBEDDED_CLI_PATH = (
    ROOT
    / "vendor"
    / "skills"
    / "overseas-energy-market-research"
    / "scripts"
    / "anysearch"
    / "anysearch_cli.py"
)
MARKET_SCRIPTS = ROOT / "vendor" / "skills" / "overseas-energy-market-research" / "scripts"


def _load_cli(path: Path):
    spec = importlib.util.spec_from_file_location("embedded_anysearch_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnySearchPythonProxyTests(unittest.TestCase):
    def test_proxy_error_retries_same_endpoint_without_environment_proxy(self) -> None:
        module = _load_cli(CLI_PATH)

        response = MagicMock()
        response.json.return_value = {"result": {"content": [{"type": "text", "text": "ok"}]}}
        direct_session = MagicMock()
        direct_session.post.return_value = response
        session_context = MagicMock()
        session_context.__enter__.return_value = direct_session

        with patch.object(module.requests, "post", side_effect=module.requests.exceptions.ProxyError("broken proxy")), patch.object(
            module.requests, "Session", return_value=session_context
        ):
            result = module._call_api("search", {"query": "test"}, "")

        self.assertEqual(result, "ok")
        self.assertFalse(direct_session.trust_env)
        direct_session.post.assert_called_once_with(
            module.ENDPOINT,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"query": "test"}},
            },
            headers=module._build_headers(""),
            timeout=30,
        )


class EmbeddedAnySearchCliProxyFallbackTests(unittest.TestCase):
    """回归：海外市场调研内嵌 CLI 必须与官方 3.0.1 一致具备 ProxyError 直连回退，
    否则代理环境变量一旦不可用，所有采集全部 network_error 归零。"""

    def test_embedded_cli_retries_directly_on_proxy_error(self) -> None:
        module = _load_cli(EMBEDDED_CLI_PATH)

        response = MagicMock()
        response.json.return_value = {"result": {"content": [{"type": "text", "text": "ok"}]}}
        direct_session = MagicMock()
        direct_session.post.return_value = response
        session_context = MagicMock()
        session_context.__enter__.return_value = direct_session

        with patch.object(module.requests, "post", side_effect=module.requests.exceptions.ProxyError("broken proxy")), patch.object(
            module.requests, "Session", return_value=session_context
        ):
            result = module._call_api("search", {"query": "test"}, "")

        self.assertEqual(result, "ok")
        self.assertFalse(direct_session.trust_env)


class MarketBackendProxyEnvTests(unittest.TestCase):
    """回归：无代理部署（容器）不得被注入不存在的本机代理；需要代理时通过
    ANYSEARCH_PROXY 显式开启。"""

    def _backend(self):
        import sys

        if str(MARKET_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(MARKET_SCRIPTS))
        from web_collection import anysearch_backend

        return anysearch_backend

    def test_proxy_env_does_not_inject_proxy_by_default(self) -> None:
        backend = self._backend()
        clean = {k: v for k, v in os.environ.items() if k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
        with patch.dict(os.environ, clean, clear=True), patch.object(backend, "PROXY_HOST", ""):
            env = backend.proxy_env()
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertIn("127.0.0.1", env["NO_PROXY"])

    def test_proxy_env_injects_proxy_when_configured(self) -> None:
        backend = self._backend()
        clean = {k: v for k, v in os.environ.items() if k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
        with patch.dict(os.environ, clean, clear=True), patch.object(backend, "PROXY_HOST", "http://127.0.0.1:7897"):
            env = backend.proxy_env()
        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7897")


class MarketBackendQuotaFakeSuccessTests(unittest.TestCase):
    """回归：额度耗尽时 API 返回 200、CLI 退出码 0，正文只有额度提示。
    旧逻辑按退出码判成功，导致真实失败被记成数百次成功采集、台账登记空转。"""

    def _backend(self):
        import sys

        if str(MARKET_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(MARKET_SCRIPTS))
        from web_collection import anysearch_backend

        return anysearch_backend

    def _completed(self, returncode: int, stdout: str) -> "object":
        import subprocess

        return subprocess.CompletedProcess(args=["cli"], returncode=returncode, stdout=stdout, stderr="")

    def test_quota_message_with_zero_exit_is_failure(self) -> None:
        backend = self._backend()
        completed = self._completed(0, "You’ve reached your API key’s total free quota for today. Please try again tomorrow.")
        result = backend._normalize(
            completed, candidates_found=0, raw_capture_path="raw_capture/x.md", cli_path=Path("cli.py")
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, backend.ErrorClass.INSUFFICIENT_BALANCE)
        self.assertIn("quota", result.error_message.casefold())

    def test_normal_zero_exit_stays_success(self) -> None:
        backend = self._backend()
        completed = self._completed(0, "Search Results (5 results)\n### 1. Germany storage quota policy overview")
        result = backend._normalize(
            completed, candidates_found=5, raw_capture_path="raw_capture/x.md", cli_path=Path("cli.py")
        )
        # 正常结果中含 “quota” 泛词不得误判（只拦精确额度耗尽话术）。
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
