"""First-run defaults must block providers and preserve explicit saved choices."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.ai.llm_engine import NebiusEngine, ProviderConfigurationError
from blob.ipc import blob_service_pb2 as pb
from blob.privacy.controls import PrivacyBlocked, PrivacyControls
from blob.skills.builtin.web import WebReadSkill
from blob.skills.registry import SkillRegistry
from test_private_service import orchestrator


@pytest.mark.asyncio
async def test_fresh_install_blocks_inference_and_web_before_dispatch(tmp_path):
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    assert not controls.cloud_enabled and not controls.state["awareness_enabled"]
    create = AsyncMock()
    engine = NebiusEngine.__new__(NebiusEngine)
    engine.controls = controls
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(PrivacyBlocked):
        await engine._create(model="synthetic", messages=[])
    create.assert_not_awaited()
    registry = SkillRegistry(tmp_path / "skills", controls=controls)
    read = WebReadSkill()
    read.async_execute = AsyncMock()
    registry.register(read)
    result = await registry.execute("web_read", {"url": "https://example.com"}, source="terminal")
    assert not result.success
    read.async_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_notice_and_opt_in_are_local_and_persist_across_restarts(tmp_path):
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    blob = orchestrator(controls)
    blob._handle_user_message = AsyncMock()
    explanation = await blob.handle_user_message(pb.UserMessage(text="/privacy explain"))
    assert "Nebius" in explanation and "not encrypted" in explanation and "does not turn off cloud chat" in explanation
    assert not controls.cloud_enabled
    response = await blob.handle_user_message(pb.UserMessage(text="/privacy cloud on"))
    assert "Cloud assistance on" in response and "memories" in response and "provider" in response
    restarted = PrivacyControls(controls.path)
    assert restarted.cloud_enabled
    assert not restarted.state["awareness_enabled"]
    restarted.check(cloud=True)
    assert controls.path.stat().st_mode & 0o777 == 0o600
    blob._handle_user_message.assert_not_awaited()


@pytest.mark.parametrize("cloud", [True, False])
def test_upgrade_preserves_legacy_cloud_choice_without_enabling_awareness(tmp_path, cloud):
    path = tmp_path / "privacy.json"
    path.write_text(json.dumps({"paused": False, "cloud_enabled": cloud,
                                "approved_folders": [], "disabled_skills": []}))
    controls = PrivacyControls(path)
    assert controls.cloud_enabled is cloud
    assert not controls.state["awareness_enabled"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", "your_nebius_api_key_here"])
async def test_local_startup_needs_no_key_and_missing_key_never_reaches_sdk(tmp_path, monkeypatch, key):
    sdk = AsyncMock()
    monkeypatch.setattr("blob.ai.llm_engine.AsyncOpenAI", sdk)
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    engine = NebiusEngine(key, "https://api.studio.nebius.ai/v1", "synthetic", controls=controls)
    assert engine._client is None
    with pytest.raises(PrivacyBlocked):
        await engine._create(model="synthetic", messages=[])
    controls.update(cloud_enabled=True)
    with pytest.raises(ProviderConfigurationError, match="needs an API key"):
        await engine._create(model="synthetic", messages=[])
    sdk.assert_not_called()
    blob = orchestrator(controls)
    blob.llm = engine
    blob._handle_user_message = AsyncMock()
    reply = await blob.handle_user_message(pb.UserMessage(text="Hello"))
    assert "needs an API key" in reply
    blob._handle_user_message.assert_not_awaited()
