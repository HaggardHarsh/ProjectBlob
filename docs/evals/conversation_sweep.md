# Multi-turn conversation sweep

`blob.evals.conversation_sweep` exercises 20 synthetic conversations containing
85 turns. It uses the real orchestrator, memory stores, privacy controls and skill
registry. Each conversation gets disposable storage. Camera and screen inputs
are fixtures; web tools expose only synthetic pages. No real desktop capture,
webcam access, face enrollment or personal-store access takes place.

The catalog covers naming and reasons, corrected names after a restart, names
after long topic changes, eight ways to ask about saved faces, ambiguous camera
acceptances and typos, unmatched enrolled faces, deletion and restart, declined
drafts, topic changes, old PDFs versus fresh screen requests, missing screen
integration, sensitive-window recovery, cloud-off, privacy pause and emotional
requests without questions.

## Two kinds of checks

Offline mode uses a fixed synthetic model response. It verifies routing, actual
tool receipts, provider boundaries, prompt evidence and persistence. It explicitly
marks model-answer checks as skipped: a scripted answer is not evidence of real
model quality. These tests run in pytest and the push/PR CI workflow; CI also
uploads a separate `conversation-sweep.json` report. No paid API runs in CI.

Live mode additionally checks the actual configured model's replies. `classic`
uses the built-in orchestration loop; `configured` uses the selected installed
runtime and transport, including Hermes/OpenShell. `both` runs both profiles.
Requests share a model-call budget, each turn has a deadline, and interrupted
runs preserve completed scenario reports with `complete: false`. Errors and
budget exhaustion fail the result. Equivalent wording is allowed, but heuristic
checks still need transcript review before a failure is called a product bug.
Reports retain synthetic requests, visible answers, tool receipts, model usage
and pass/fail reasons; credentials and hidden reasoning are excluded.

```bash
# Offline host checks; no provider usage.
venv/bin/python -m blob.evals.conversation_sweep \
  --report .runtime/validation/conversation-sweep-offline.json

# Actual model answers; synthetic inputs and normal provider charges.
venv/bin/python -m blob.evals.conversation_sweep --live --runtime both \
  --max-calls 80 --report .runtime/validation/conversation-sweep-live.json

# Recheck one failed conversation without repeating the entire live run.
venv/bin/python -m blob.evals.conversation_sweep --live --runtime both \
  --case name_reason_and_correction --max-calls 16 \
  --report .runtime/validation/conversation-sweep-name-recheck.json
```

## Findings on 2026-10-22

The first offline pass failed 6 of 20 conversations, spanning 19 turns. Four
face-memory phrasings missed local enrollment lookup, "go for it" missed the
camera reminder, and missing window metadata still produced a generic privacy
message. The fixed offline catalog passed all 20 conversations / 85 turns.

The real-model run used NVIDIA Nemotron Super through the classic loop and
Hermes/OpenShell: 40 conversations / 170 turns, using 50 provider requests.
38 conversations passed. Both runtimes reverted to the obsolete name after a
restart despite receiving the corrected name in the system prompt. Superseded
user declarations in retrieved episodes were the conflicting evidence.

Ordinary recall now omits superseded naming declarations without deleting the
archive or suppressing explicit history queries. The targeted live recheck
passed on both runtimes: 2 conversations / 12 turns, using 12 provider requests.
The full backend tests also exposed a tight-context regression: growing camera
instructions crowded a recent draft correction out of a 16 KB prompt. The camera
instructions were shortened while preserving their requirements.
The final backend regression run passed all 903 tests.

Screen failures now distinguish an unverified active window/bridge, a sensitive
window and manual pause. Capture checks use the current window rather than a
stale polled shield flag. Missing metadata still blocks capture. These are
synthetic integration checks, not certification of a user's real compositor,
extension installation or camera match quality.

See the [sanitized run summary](conversation_sweep.json) for before/after findings
and the actual failed and repaired naming transcripts. This is a regression
baseline, not a claim that every possible conversation works. Add new discovered
sequences to `catalog()` and rerun the affected case when prompts, routing or
memory behavior change.
