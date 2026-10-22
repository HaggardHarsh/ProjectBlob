"""Keep the conversation catalog and its failure signals in ordinary CI."""

import pytest

from blob.evals.conversation_sweep import Turn, catalog, evaluate, response_checks, run


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", catalog(), ids=lambda scenario: scenario.name)
async def test_offline_conversation_scenario(tmp_path, scenario):
    result = await evaluate(tmp_path, scenario, "classic", live=False, budget=[80])
    assert result["passed"], result
    assert len(result["turns"]) == len(scenario.turns)


def test_semantic_check_rejects_name_backtracking_but_offline_does_not_claim_to_test_the_model():
    turn = Turn("Why that so", model_pattern=r"you asked", model_avoid=("misspoken",))
    checks, skipped = response_checks(turn, "I must have misspoken.", [], [], [], live=True)
    assert not checks["model_answer"] and not skipped
    checks, skipped = response_checks(turn, "Synthetic offline reply.", [], [], [], live=False)
    assert "model_answer" not in checks and skipped


def test_actions_and_provider_calls_are_checked_independently_of_success_claims():
    turn = Turn("do ti", provider="forbidden")
    checks, _ = response_checks(turn, "I opened the camera.", [{"name": "camera"}], [{}], [], live=False)
    assert not checks["expected_tools"] and not checks["provider_boundary"]
    checks, _ = response_checks(Turn("What do you call me?", system_quote="Call me Luma."),
                              "Luma.", [], [{}], ["No naming evidence."], live=False)
    assert not checks["original_user_evidence_in_prompt"]


@pytest.mark.asyncio
async def test_sweep_reports_partial_or_budget_exhausted_runs_as_failures():
    report = await run(cases=["name_reason_and_correction"], max_calls=1)
    assert not report["passed"]
    assert report["counts"]["failed_turns"] > 0
    assert report["counts"]["provider_calls"] == 0
    assert report["counts"]["model_requests"] == 1


@pytest.mark.asyncio
async def test_sweep_rejects_unknown_cases_instead_of_passing_an_empty_catalog():
    with pytest.raises(ValueError, match="existing conversation"):
        await run(cases=["missing"])
