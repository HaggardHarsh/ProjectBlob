from blob.ai.context_budget import OMITTED_CONTEXT, fit_messages, prompt_size_bytes


def _message(role, content):
    return {"role": role, "content": content}


def test_prompt_size_counts_utf8_bytes_and_message_overhead():
    assert prompt_size_bytes([_message("user", "é")]) == 66


def test_budget_drops_old_turn_pair_before_current_request_or_tool_result():
    system = _message("system", "System")
    background = _message("user", "Historical background:\nRelevant fact")
    old_user = _message("user", "old question " * 40)
    old_reply = _message("assistant", "old answer " * 40)
    current = _message("user", "Current question")
    observation = _message("user", "[Observation] Verified result")
    messages = [system, background, old_user, old_reply, current, observation]
    limit = prompt_size_bytes([system, background, current, observation])

    fitted = fit_messages(messages, current, limit)

    assert fitted == [system, background, current, observation]
    assert messages[2] == old_user
    assert prompt_size_bytes(fitted) <= limit


def test_budget_trims_background_only_at_complete_lines():
    system = _message("system", "System")
    background = _message("user", "Historical background:\nfirst fact\nsecond fact\n" +
                          "third fact " * 20)
    current = _message("user", "Current question")
    observation = _message("user", "[Observation] Keep this result")
    retained = "Historical background:\nfirst fact\n"
    limit = (prompt_size_bytes([system, current, observation]) + 64 +
             len((retained + OMITTED_CONTEXT).encode("utf-8")))

    fitted = fit_messages([system, background, current, observation], current, limit)

    assert fitted is not None
    assert "first fact" in fitted[1]["content"]
    assert "second fact" not in fitted[1]["content"]
    assert fitted[1]["content"].endswith(OMITTED_CONTEXT)
    assert fitted[-2:] == [current, observation]


def test_budget_omits_background_when_essential_messages_barely_fit():
    system = _message("system", "System")
    background = _message("user", "Historical background:\n" + "old " * 100)
    current = _message("user", "Current question")
    observation = _message("user", "[Observation] Keep this result")
    limit = prompt_size_bytes([system, current, observation])

    assert fit_messages([system, background, current, observation], current, limit) == [
        system, current, observation,
    ]


def test_budget_refuses_to_cut_latest_request_or_tool_result():
    system = _message("system", "System")
    background = _message("user", "Historical background:\nold")
    current = _message("user", "Current question")
    observation = _message("user", "[Observation] " + "large result " * 100)

    assert fit_messages([system, background, current], current,
                        prompt_size_bytes([system, current]) - 1) is None
    assert fit_messages([system, background, current, observation], current,
                        prompt_size_bytes([system, current, observation]) - 1) is None


def test_latest_exchange_survives_large_background_and_old_turns():
    system = _message("system", "System")
    background = _message("user", "Historical background:\n" + "Old memory\n" * 100)
    old = [_message("user", "Old question"), _message("assistant", "Old answer")]
    latest = [_message("user", "Use a friendly tone and keep the subject line."),
              _message("assistant", "Subject: Extension request\nDear Professor...")]
    current = _message("user", "Make it shorter")
    observation = _message("user", "[Observation] Confirmed tool result")
    essential = [system, *latest, current, observation]
    fitted = fit_messages([system, background, *old, *latest, current, observation],
                          current, prompt_size_bytes(essential) + 150)

    assert fitted is not None
    assert fitted[-4:] == [*latest, current, observation]
    assert not any(item in fitted for item in old)
    assert prompt_size_bytes(fitted) <= prompt_size_bytes(essential) + 150
    assert background["content"].endswith("Old memory\n")


def test_latest_exchange_survives_when_only_background_must_be_removed():
    system = _message("system", "System")
    background = _message("user", "Historical background:\n" + "Old memory\n" * 100)
    latest = [_message("user", "Keep the blue design"), _message("assistant", "Blue design ready")]
    current = _message("user", "Explain it")
    expected = [system, *latest, current]
    assert fit_messages([system, background, *latest, current], current,
                        prompt_size_bytes(expected)) == expected
