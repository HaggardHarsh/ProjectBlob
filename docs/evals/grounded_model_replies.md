# Grounded model replies verification

Verified on 2026-10-17 with the configured Nebius model, real Hermes worker in
OpenShell, public web tools, and a temporary conversation store.

[Live results](grounded_model_replies.json) replay the reported questions:

| Question | Observed behavior |
| --- | --- |
| what is gemini 4 argon | Search and page reading ran before inference; the answer cited an official source. |
| crazy, is it good? | The earlier user question supplied the subject; a fresh source read supported the answer, which distinguished vendor claims from independent evaluation. |

Both inference runs used one model call and executed no shell or reminder tools.
Some page reads failed; the follow-up successfully re-read the same product's
previously verified URL. Both replies contained a source URL and no raw tool
serialization. This checks source retrieval and tool receipts, not independent
verification of every statement in a model answer or the model's quality.

Deterministic regressions replay the malformed transcript from the report, check
one bounded format retry, reject repeated malformed responses, and verify no
generated textual actions execute. They also cover streamed display, conversation
history, unavailable or irrelevant sources, tool scoping, and privacy reset.
The complete backend suite passed **570 tests** (46 dependency deprecation warnings).
