from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "vendor" / "skills" / "anysearch" / "scripts" / "anysearch_cli.py"


class AnySearchPythonProxyTests(unittest.TestCase):
    def test_proxy_error_retries_same_endpoint_without_environment_proxy(self) -> None:
        spec = importlib.util.spec_from_file_location("embedded_anysearch_cli", CLI_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

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


if __name__ == "__main__":
    unittest.main()
