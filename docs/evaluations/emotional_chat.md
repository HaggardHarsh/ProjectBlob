# Emotional conversation evaluation

Tested on 2026-10-20 with the configured
`nvidia/nemotron-3-super-120b-a12b` model, through Hermes/OpenShell and the
classic chat loop. These are actual provider replies through Blob's
orchestrator, with temporary isolated memory stores and fixture web tools.

## What changed

The personality prompt now describes how to engage with an ongoing emotional
conversation: respond to the newest detail, avoid repeating offers to listen,
respect rejected suggestions, allow replies without questions, and actually
start a requested distraction.

The host notices support offers in the last three assistant replies and adds
a reminder to move the conversation forward. On tool-free chat turns, a repeated
offer or a question against an explicit “no questions” request gets at most one
revision. The rejected draft is buffered and is not displayed or remembered when
a usable replacement succeeds. The revision cannot execute tools.

The correction has a 20-second timeout and respects the prompt budget. If it
fails, the original reply is retained. Explicit reassurance requests and
recognizable safety-related content are excluded from the repetition correction.
These checks are narrow style heuristics, not mental-health classification.

## Checks and transcripts

- **113 local tests passed**, covering ordinary and streamed chat, the native
  runtime, recent-history delivery, context budgets, revision failure,
  cancellation, tool restrictions, emotes, memory, and conversation closure.
- [Configured-runtime development run](emotional_chat_live.json): 24 turns in
  eight scenarios; 7/8 recorded scenario checks passed. The failure was a
  rhetorical question after a no-questions request; an explicit boundary check
  was added afterward.
- [Broader configured-runtime rerun](emotional_chat_verified.json): 24 turns,
  26 provider calls. The saved scorer recorded 7/8 passing. Manual review found
  another missed availability phrase, “Just here if anything shifts,” in the
  hostel conversation. The final phrase detector flags that case too; the
  detector was expanded and the hostel case was rerun separately.
- [Final classic-runtime follow-up](emotional_chat_followup.json): all three
  selected scenarios passed across 10 turns and 12 provider calls: the full
  hostel conversation, recovery with the original bad replies still in history,
  and rejected advice followed by a no-questions distraction.
- [Final configured-runtime hostel check](emotional_chat_hostel.json): the full
  six-turn conversation passed with seven provider calls, including one
  corrective generation. The final reply addressed being away from family and
  suggested a familiar photo or song rather than repeating an invitation to vent.

The eight scenarios cover homesickness, grief, rejection, unwanted advice,
mixed joy and embarrassment, anger and correction, an explicit self-harm
disclosure, and recovery from the supplied repetition loop.

## Qualitative limits

The loop is improved, but these checks do not establish consistently high
emotional quality. Some live replies still sounded formulaic or offered generic
coping suggestions. Earlier runs also included an inappropriate “Me too” when
the user described exhaustion. The prompt discourages invented experience; the
style detector does not attempt to catch every such claim.

The broader rerun's urgent-distress reply encouraged immediate human help but
omitted a direct immediate-safety question. Other runs did ask it. This remains
an inconsistency, and is recorded as a failed check. Crisis replies are not
rewritten merely to satisfy the style checks. No clinical-safety claim is made
by these tests.

Read the transcripts as well as the counters. The reports retain failed runs
and intermediate detector results rather than presenting only successful
samples.

## Reproduce

```bash
venv/bin/python -m pytest \
  backend_python/tests/test_emotional_conversation.py \
  backend_python/tests/test_model_continuity.py \
  backend_python/tests/test_conversation_closure.py \
  backend_python/tests/test_reply_presentation.py \
  backend_python/tests/test_context_budget.py \
  backend_python/tests/test_guardrails.py \
  backend_python/tests/test_agent_runtime.py -q

venv/bin/python -m blob.evals.emotional_conversation \
  --live --report /tmp/blob-emotional-chat.json
```

Live evaluation uses the configured provider and normal API billing. Use
`--runtime classic` to test the classic route, and repeat `--case` to select
individual scenarios.
