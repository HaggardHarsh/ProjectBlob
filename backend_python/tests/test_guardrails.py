from blob.ai.guardrails import unsupported_personal_event_claim
from datetime import datetime, timedelta


def test_personal_event_claim_requires_user_evidence():
    claim = "Yep, your presentation is tomorrow."
    assert unsupported_personal_event_claim(claim, ["What presentation?", "I have no presentation."])
    assert not unsupported_personal_event_claim(claim, ["I have a presentation tomorrow."])
    assert not unsupported_personal_event_claim("I don't know if your presentation is tomorrow.", [])
    assert not unsupported_personal_event_claim("Is your presentation tomorrow?", [])


def test_new_user_correction_beats_older_plan():
    claim = "Your presentation is tomorrow."
    assert unsupported_personal_event_claim(
        claim, ["I have no presentation.", "I have a presentation tomorrow."])
    assert not unsupported_personal_event_claim(
        claim, ["Actually, I have a presentation tomorrow.", "I have no presentation."])
    assert unsupported_personal_event_claim(claim, ["My presentation was canceled."])


def test_each_personal_event_claim_needs_its_own_support():
    assert unsupported_personal_event_claim(
        "Your presentation is tomorrow, and your exam is Friday.",
        ["I have a presentation tomorrow."],
    )


def test_old_relative_date_does_not_support_tomorrow_claim():
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).timestamp()
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).date().isoformat()
    claim = "Your presentation is tomorrow."

    assert unsupported_personal_event_claim(
        claim, [("I have a presentation tomorrow.", yesterday)])
    assert unsupported_personal_event_claim(claim, ["I have a presentation."])
    assert not unsupported_personal_event_claim(
        claim, [(f"I have a presentation on {tomorrow}.", yesterday)])
