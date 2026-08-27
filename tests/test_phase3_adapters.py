from __future__ import annotations

import inspect
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from energy_research_agent.adapters.anysearch import AnySearchCliAdapter
from energy_research_agent.adapters.base import AdapterHealth, SearchRequest
from energy_research_agent.adapters.kimi_webbridge import KimiWebBridgeSearchAdapter


class Phase3AdapterTests(unittest.TestCase):
    def _request(self) -> SearchRequest:
        return SearchRequest(
            query_id="QUERY-Q001",
            query="示例企业 官网",
            entity_id="ENT-1",
            purpose="identity evidence",
        )

    def test_missing_anysearch_dependency_fails_closed(self) -> None:
        adapter = AnySearchCliAdapter(skill_root=Path("definitely-missing-anysearch"))
        self.assertFalse(adapter.health().available)
        result = adapter.search(self._request())
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.hits, [])

    def test_anysearch_can_discover_bundled_cli_runtime(self) -> None:
        adapter = AnySearchCliAdapter()
        prefix = adapter._command_prefix()
        self.assertIsNotNone(prefix)
        self.assertIn("vendor", prefix[-1])
        self.assertTrue(prefix[-1].endswith("anysearch_cli.py"))
        self.assertTrue(adapter.health().available)

    def test_anysearch_vertical_search_requires_discovery(self) -> None:
        request = self._request().model_copy(update={"metadata": {"domain": "business"}})
        result = AnySearchCliAdapter().search(request)
        self.assertEqual(result.status, "blocked")
        self.assertIn("get_sub_domains", " ".join(result.diagnostics))

    def test_anysearch_zero_exit_quota_notice_is_not_a_search_hit(self) -> None:
        adapter = AnySearchCliAdapter()
        prefix = [["python", "anysearch_cli.py"]]
        quota = subprocess.CompletedProcess(
            prefix[0], 0,
            "You’ve reached your API key’s total free quota for today. Please try again tomorrow.",
            "",
        )
        with patch.object(adapter, "health", return_value=AdapterHealth(name="anysearch", available=True, version="3.0.1")), \
             patch.object(adapter, "_command_prefixes", return_value=prefix), \
             patch("energy_research_agent.adapters.anysearch.subprocess.run", return_value=quota):
            result = adapter.search(self._request())
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.hits, [])
        self.assertIn("quota", " ".join(result.diagnostics).casefold())

    def test_anysearch_runtime_account_override_never_enters_process_argv(self) -> None:
        adapter = AnySearchCliAdapter()
        request = self._request()
        previous = os.environ.get("ERA_ANYSEARCH_API_KEY")
        os.environ["ERA_ANYSEARCH_API_KEY"] = "alternate-runtime-key"
        try:
            command = adapter._build_command(
                ["python", "anysearch_cli.py"], request,
                url=None, domain=None, sub_domain=None, sub_domain_params=None,
            )
        finally:
            if previous is None:
                os.environ.pop("ERA_ANYSEARCH_API_KEY", None)
            else:
                os.environ["ERA_ANYSEARCH_API_KEY"] = previous
        self.assertEqual(command[:2], ["python", "anysearch_cli.py"])
        self.assertNotIn("alternate-runtime-key", command)
        self.assertNotIn("--api_key", command)
        self.assertIn("search", command)

    def test_anysearch_adapter_has_no_unapproved_backend_dependency(self) -> None:
        source = inspect.getsource(AnySearchCliAdapter).lower()
        self.assertNotIn("web-rooter", source)
        self.assertNotIn("web_access", source)

    def test_anysearch_falls_through_to_node_after_python_transport_failure(self) -> None:
        adapter = AnySearchCliAdapter()
        prefixes = [["python", "anysearch_cli.py"], ["node", "anysearch_cli.js"]]
        failed = subprocess.CompletedProcess(prefixes[0], 1, "", "Connection Error: Unable to reach the API endpoint.")
        recovered = subprocess.CompletedProcess(prefixes[1], 0, "## Search Results\n\n### 1. Example\n- **URL**: https://example.com", "")
        with patch.object(adapter, "health", return_value=AdapterHealth(name="anysearch", available=True, version="3.0.1")), \
             patch.object(adapter, "_command_prefixes", return_value=prefixes), \
             patch("energy_research_agent.adapters.anysearch.subprocess.run", side_effect=[failed, recovered]):
            result = adapter.search(self._request())
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.hits), 1)
        self.assertIn("recovered with js", " ".join(result.diagnostics))

    def test_disconnected_kimi_bridge_fails_closed(self) -> None:
        class DisconnectedKimi(KimiWebBridgeSearchAdapter):
            @staticmethod
            def _binary():
                return None

        # daemon 不可达：本地二进制缺失 + HTTP 探测失败 → fail-closed。
        # 探测走模拟 OSError，不做真实网络 I/O（保证离线/代理环境下确定性）。
        import urllib.request
        original = urllib.request.urlopen

        def _unreachable(*_args, **_kwargs):
            raise OSError("daemon unreachable (simulated)")

        urllib.request.urlopen = _unreachable
        try:
            result = DisconnectedKimi("fixture-session", daemon_url="http://127.0.0.1:9").search(self._request())
        finally:
            urllib.request.urlopen = original
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.hits, [])

    def test_kimi_command_unwraps_daemon_data(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read():
                return b'{"ok":true,"data":{"title":"example"}}'

        module = __import__("urllib.request", fromlist=["build_opener"])
        original = module.build_opener

        class Opener:
            @staticmethod
            def open(*_args, **_kwargs):
                return Response()

        module.build_opener = lambda *_args, **_kwargs: Opener()
        try:
            result = KimiWebBridgeSearchAdapter("fixture")._command("snapshot", {})
        finally:
            module.build_opener = original
        self.assertEqual(result, {"title": "example"})


if __name__ == "__main__":
    unittest.main()
