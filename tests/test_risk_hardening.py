"""风险加固测试：视觉核验网关复用 / 浏览器发现链 / 无浏览器 Word 降级。

对应剩余风险修正：
- 风险1:视觉核验复用既有研究网关凭据（ERA_OPENAI_API_KEY），无需新增外部配置
- 风险3:浏览器发现链含 Playwright 托管 Chromium 缓存；无浏览器时 Word 确定性降级
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from energy_research_agent.artifacts.diagram_design_adapter import DiagramDesignAdapter
from energy_research_agent.artifacts.word import FrozenWordPublisher
from energy_research_agent.domain.enums import ArtifactType, RunStatus, VerificationStatus
from energy_research_agent.domain.ids import new_sortable_id
from energy_research_agent.domain.models import ExtractedEvidenceBatch, RunManifest
from energy_research_agent.evidence.freeze import FreezeService
from energy_research_agent.evidence.store import EvidenceStore
from energy_research_agent.graph.phase3_runner import Phase3Runner
from energy_research_agent.graph.state import ResearchState
from energy_research_agent.research.vision import GatewayVisionVerifier, default_vision_verifier
from energy_research_agent.settings import Settings, load_yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_bundle(temp: str):
    raw = json.loads((ROOT / "tests" / "fixtures" / "normal_manufacturer.json").read_text(encoding="utf-8"))
    company = raw[0]["entities"][0]["canonical_name"]
    run_id, request_id = new_sortable_id("RUN"), new_sortable_id("REQ")
    store = EvidenceStore(Path(temp) / "evidence.sqlite3")
    store.create_run(RunManifest(
        run_id=run_id, request_id=request_id, status=RunStatus.RUNNING,
        config_hash="fixture", code_version="0.9.1", model_gateway={"mode": "fixture"},
    ))
    state, manifest, _ = Phase3Runner(store, load_yaml(ROOT / "config" / "enterprise_rules.yaml")).process_batches(
        ResearchState(run_id=run_id, request_id=request_id, status=RunStatus.RUNNING), company,
        [ExtractedEvidenceBatch.model_validate(item) for item in raw], output_dir=Path(temp) / "freeze",
    )
    return FreezeService(store).load_bundle(state.freeze_id), manifest


class RiskHardeningTests(unittest.TestCase):
    def _fake_settings(self, *, deepseek_key=None, openai_key=None, provider="auto",
                       deepseek_base="https://api.deepseek.com",
                       openai_base="https://api.openai.com/v1",
                       vision_key=None, vision_base="https://api.deepseek.com"):
        return mock.Mock(
            deepseek_api_key=deepseek_key, openai_api_key=openai_key,
            vision_provider=provider, deepseek_api_base=deepseek_base,
            openai_api_base=openai_base,
            vision_api_key=vision_key, vision_api_base=vision_base,
            deepseek_vision_model="deepseek-v4-flash-vision-exp",
            openai_vision_model="gpt-4o-mini",
        )

    def test_vision_verifier_prefers_deepseek_v4_flash_vision_exp(self) -> None:
        with mock.patch("energy_research_agent.settings.Settings",
                        return_value=self._fake_settings(deepseek_key="sk-deepseek-test")):
            verifier = default_vision_verifier()
            self.assertIsNotNone(verifier, "已配置 DeepSeek 网关凭据时视觉核验应自动可用")
            self.assertIsInstance(verifier, GatewayVisionVerifier)
            self.assertEqual(verifier.endpoint, "https://api.deepseek.com")
            self.assertEqual(verifier.model, "deepseek-v4-flash-vision-exp")

    def test_vision_verifier_falls_back_to_openai_when_no_deepseek_key(self) -> None:
        with mock.patch("energy_research_agent.settings.Settings",
                        return_value=self._fake_settings(openai_key="sk-openai-test",
                                                         openai_base="https://gateway.example.com/v1")):
            verifier = default_vision_verifier()
            self.assertIsNotNone(verifier)
            self.assertEqual(verifier.endpoint, "https://gateway.example.com/v1")
            self.assertEqual(verifier.model, "gpt-4o-mini")

    def test_vision_verifier_prefers_dedicated_vision_credentials(self) -> None:
        # 研究网关指向第三方（如 SiliconFlow）时，视觉链仍走原生 DeepSeek
        # 视觉模型专用凭据，不受研究网关改道影响。
        with mock.patch("energy_research_agent.settings.Settings",
                        return_value=self._fake_settings(
                            deepseek_key="sk-siliconflow",
                            deepseek_base="https://api.siliconflow.cn/v1",
                            vision_key="sk-native-vision",
                            vision_base="https://api.deepseek.com")):
            verifier = default_vision_verifier()
            self.assertIsNotNone(verifier)
            self.assertEqual(verifier.endpoint, "https://api.deepseek.com")
            self.assertEqual(verifier.model, "deepseek-v4-flash-vision-exp")

    def test_vision_verifier_absent_when_nothing_configured(self) -> None:
        with mock.patch("energy_research_agent.settings.Settings",
                        return_value=self._fake_settings()):
            verifier = default_vision_verifier()
        self.assertIsNone(verifier, "无任何视觉能力配置时必须诚实返回 None")

    def test_settings_reads_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_path = Path(temp) / ".env"
            env_path.write_text(
                "ERA_DEEPSEEK_API_KEY=sk-from-dotenv\nERA_OPENAI_API_KEY=sk-openai-dotenv\n",
                encoding="utf-8",
            )
            settings = Settings(_env_file=env_path)
            self.assertEqual(settings.deepseek_api_key, "sk-from-dotenv")
            self.assertEqual(settings.openai_api_key, "sk-openai-dotenv")

    def test_visual_verify_runs_on_archived_bytes(self) -> None:
        from energy_research_agent.domain.models import ImageEvidence
        from energy_research_agent.research.image_validator import ImageValidator
        from energy_research_agent.research.vision import VisionVerdict

        with tempfile.TemporaryDirectory() as temp:
            asset = Path(temp) / "photo.png"
            asset.write_bytes(b"\x89PNG-fake-bytes")
            image = ImageEvidence(
                image_id="IMG-V", entity_id="E1", source_url="https://x.example/p.png",
                source_page_url="https://x.example/", source_id="S1", source_domain="x.example",
                image_type="product", sha256="0" * 64, phash="0" * 16, width=800, height=600,
                mime_type="image/png", local_asset_ref=str(asset),
                verification_status=VerificationStatus.VERIFIED, confidence=0.9,
                target_entity_type="product", target_entity_id="E1",
            )

            def fake_vision(image, image_bytes):
                self.assertIsNotNone(image_bytes, "归档后视觉核验必须拿到本地字节")
                return VisionVerdict(verified=True, score=0.9, description="产品实景照片", entity_matched=True)

            result = ImageValidator(vision_verifier=fake_vision).visual_verify([image])[0]
            self.assertTrue(result.visual_verified)
            self.assertEqual(result.verification_method, "vision")
            self.assertEqual(result.visual_description, "产品实景照片")

            # no bytes available → never promoted
            no_bytes = image.model_copy(update={"local_asset_ref": None})
            result = ImageValidator(vision_verifier=fake_vision).visual_verify([no_bytes])[0]
            self.assertFalse(result.visual_verified)

    def test_browser_executable_finds_playwright_managed_chromium(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # legacy layout
            legacy = root / "chromium-1187" / "chrome-win" / "chrome.exe"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"MZ-fake-chrome")
            with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": temp}, clear=False):
                found = DiagramDesignAdapter._browser_executable()
            self.assertEqual(found, str(legacy))

    def test_browser_executable_finds_modern_playwright_64bit_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            modern = root / "chromium-1223" / "chrome-win64" / "chrome.exe"
            modern.parent.mkdir(parents=True)
            modern.write_bytes(b"MZ-fake-chrome")
            headless = root / "chromium_headless_shell-1223" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"
            headless.parent.mkdir(parents=True)
            headless.write_bytes(b"MZ-fake-shell")
            with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": temp}, clear=False):
                found = DiagramDesignAdapter._browser_executable()
            self.assertIn(found, {str(modern), str(headless)})

    def test_word_publisher_degrades_to_table_without_any_browser(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle, manifest = _load_bundle(temp)
            binding = next(item for item in manifest.artifacts if item.type == ArtifactType.WORD)
            target = Path(temp) / "report.docx"
            with mock.patch.object(DiagramDesignAdapter, "export_png", return_value=False):
                result = FrozenWordPublisher().publish(bundle, binding, target)
            self.assertEqual(result.status, "published", "无浏览器时 Word 仍必须发布（降级为表格）")
            with zipfile.ZipFile(target) as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
            # 无 PNG → 图降级为同源数据三线表；insight 保留
            self.assertEqual(document_xml.count("<w:drawing>"), 0)
            self.assertIn("<w:tbl>", document_xml)
            qa = json.loads((target.parent / "report_assets" / "publication_qa_report.json").read_text(encoding="utf-8"))
            visual_entries = {item["visual_id"]: item for item in qa["visual_entries"]}
            self.assertTrue(any(item["png_status"] == "unavailable" for item in visual_entries.values()))


if __name__ == "__main__":
    unittest.main()
