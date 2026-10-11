from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.evals.private_workflow import Events, make_assistant, close_assistant, run_workflow
from blob.privacy.controls import PrivacyBlocked


@pytest.mark.asyncio
async def test_nvidia_memory_is_independent_and_shares_privacy_controls(tmp_path):
    blob = make_assistant(tmp_path, Events(), [], live=False)
    try:
        assert blob.llm.model_name == blob.config.model_name
        assert blob.semantic.llm.model_name == "nvidia/Nemotron-3_5-Lightning"
        assert blob.semantic.llm is not blob.llm
        assert blob.semantic.llm.controls is blob.llm.controls is blob.controls
        blob.episodic.add_episode("I like study plans.", "You are an astronaut.")
        # Test the provider boundary used by the real background worker.
        create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="L1"))]))
        blob.semantic.llm.client.chat.completions.create = create
        del blob.semantic.llm.generate  # Restore the actual engine method.
        assert await blob.semantic.consolidate_once() == 1
        create.assert_awaited_once()
        assert create.call_args.kwargs["model"] == "nvidia/Nemotron-3_5-Lightning"
        facts = blob.semantic.list_facts()
        assert [item["text"] for item in facts] == ["I like study plans."]
        assert facts[0]["metadata"]["consolidation_model"] == "nvidia/Nemotron-3_5-Lightning"
        assert "astronaut" not in create.call_args.kwargs["messages"][-1]["content"]
        blob.controls.update(cloud_enabled=False)
        with pytest.raises(PrivacyBlocked):
            await blob.semantic.llm.generate("test", "", "test")
        assert create.await_count == 1
    finally:
        await close_assistant(blob)


@pytest.mark.asyncio
async def test_failed_nvidia_request_leaves_episodes_pending_without_chat_fallback(tmp_path):
    blob = make_assistant(tmp_path, Events(), [], live=False)
    try:
        blob.episodic.add_episode("I like study plans.", "Okay.")
        blob.semantic.llm.generate = AsyncMock(side_effect=RuntimeError("provider unavailable"))
        blob.llm.generate = AsyncMock()
        assert await blob.semantic.consolidate_once() == 0
        assert len(blob.vector_store.unconsolidated_episodes()) == 1
        assert not blob.semantic.list_facts()
        blob.llm.generate.assert_not_called()
    finally:
        await close_assistant(blob)


@pytest.mark.asyncio
async def test_private_workflow_from_memories_to_persistent_reminder(tmp_path):
    report = await run_workflow(tmp_path)
    assert report["provider_calls"] == []
    assert all(item["passed"] for item in report["results"]), report["results"]
