# Proactive conversation audit

Sanitized machine-readable evidence: [conversation_audit.json](conversation_audit.json).

The audit uses observable tool receipts and isolated stores as well as response
checks. It does not rely on a model claiming that an action succeeded. The live
mode uses the configured inference API, synthetic conversations, fixed untrusted
webpages and disposable memory/reminder databases. It never sends mail, books
travel, captures the desktop/camera or reads the desktop's personal stores.

## Findings fixed

- Natural travel requests such as “Can you see if any flights are available?”
  were missed. Changed-date follow-ups could lose the journey or re-read an old
  page without searching for the new date.
- “Don't search the web again” could trigger preflight retrieval. Unrelated chat
  containing “it” could inherit web permission from a previous task.
- The classic runtime's printed tool-call protocol failed on real model output:
  duplicate JSON objects and a fictional success reply appeared in one completion.
  It now supplies request-authorized native function schemas and adapts one
  structured call to the host loop. Multiple, unknown or invalid calls execute
  nothing. Tools still pass through the same argument and privacy controls.
- Valid citations using `【URL】` or trailing invisible separators were rejected.
  Missing citations now receive one answer-only correction using checked source
  evidence, with tools disabled. Invented URLs remain rejected.
- Provider tokens outside the original tool-token family could reach the chat
  and recent history. Reserved/start/end tokens now trigger bounded correction
  and stay out of streamed previews, replies and saved conversation history.
- Automatic screen shielding blocked recent conversation updates along with disk
  writes. The session now retains corrections in memory while persistence stays
  blocked. Manual privacy pause still blocks new conversations.

## Evidence

Verified 2026-10-18 on Fedora 44 with the configured
`nvidia/nemotron-3-super-120b-a12b` model. The initial audit passed 26 of 52 checks;
failures were investigated rather than accepted as a release result. The final
catalog includes additional regressions found during that investigation.

| Check | Result |
| --- | --- |
| Complete backend regression suite | 741 passed, 46 dependency deprecation warnings |
| Request/protocol boundary catalog | 28/28 |
| Real-model classic conversation sequence | 14/14, 17 provider calls |
| Real-model Hermes/OpenShell conversation sequence | 14/14, 18 provider calls |
| Live memory classification → saved document plan → reopened reminder → cloud-off/pause | 11/11, 5 provider calls |
| Real keyless search, model-grounded official page read and sandboxed public browser | 3/3, 2 provider calls |
| Existing C++ rendering, attachment IPC, startup and animation checks | 4/4 |
| Source distribution → wheel → installed package outside checkout | Passed: packaged resources, authenticated IPC, privacy defaults, missing-key errors and reminder delivery/acknowledgement |

The two conversation sequences check release facts, missing pricing, travel and
changed dates, stopping web use, exactly one reminder creation, webpage prompt
injection, drafting/declining/acknowledging, corrections during screen shielding,
failed sources and cloud-off. An unusable format/source fallback fails the live
audit even if it safely avoids an unsupported claim. Assertions allow equivalent
wording; a failure still needs investigation to distinguish a product bug from
an overly narrow test oracle.

Web evidence in the conversation catalog is synthetic and does not prove live
ticket inventory. The independent public-network smoke uses read-only pages.
Model behavior remains nondeterministic: one passing sequence is evidence, not
proof that all conversations work. Reports contain synthetic completions and
usage metadata, not credentials or hidden reasoning fields.
The wheel check reused the verified dependency environment through a disposable
environment; clean dependency installation remains covered by hosted CI.

The developer environment's `pip check` also reported a pre-existing optional
RapidOCR dependency mismatch: its metadata requires `opencv-python`, while this
workstation uses `opencv-contrib-python`. The locked release dependency closure
matches its baseline; hosted CI checks a clean installation. No overlapping
OpenCV distribution was added to the live environment during this audit. OCR
optional-dependency packaging remains separate from these conversation fixes.

## Reproduce

Without provider usage (also runs automatically in CI):

```bash
venv/bin/python -m pytest backend_python/tests -q
venv/bin/python -m blob.evals.conversation_audit --report .runtime/validation/conversation-boundaries.json
```

With the real provider and synthetic stores (normal inference charges):

```bash
venv/bin/python -m blob.evals.conversation_audit --live --runtime both --max-calls 60 --report .runtime/validation/conversation-audit.json
venv/bin/python -m blob.evals.private_workflow --live --report .runtime/validation/private-workflow.json
```

`classic` tests the built-in loop; `configured` uses the installation's selected
runtime and transport. `both` runs those two profiles. Hermes must already be
installed when selected; an unavailable runtime is a failure, not a silent
fallback. The call limit spans both conversation profiles, and each turn has a
deadline. Repeated failures, API outages and exhausted budgets fail the report.

Push/PR CI runs the deterministic catalog and unit/integration regressions with
a synthetic provider key, then uploads `conversation-audit.json`. It does not
run paid inference automatically or upload the workstation's API key. Run the
live audit when changing prompts, model configuration or tool orchestration.
