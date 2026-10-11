# NVIDIA memory and a private assistant workflow

Blob uses NVIDIA Nemotron for a recurring task that makes persistent personal
memory useful. The exact Nebius catalog ID is `nvidia/Nemotron-3_5-Lightning`.
Chat and document answers continue using `zai-org/GLM-5.3-Flash`.

```dotenv
BLOB_MODEL_NAME=zai-org/GLM-5.3-Flash
BLOB_MEMORY_MODEL_NAME=nvidia/Nemotron-3_5-Lightning
```

Both use the existing `NEBIUS_API_KEY` and Nebius endpoint. Restart the backend
after changing configuration. The background worker checks for unconsolidated
episodes every 60 seconds. Clear academic declarations are also saved immediately,
so they do not depend on waiting for consolidation.

NVIDIA receives numbered sentences from the user's side of conversation episodes,
with instructions to select lasting facts (`L1`) or expiring project/event facts
(`M2`). Assistant replies are excluded from this request. The backend validates
the codes and saves the original user wording, original source date, source episode,
and `consolidation_model`. It never stores a model-written paraphrase as a grounded
fact. A failed request leaves the episodes pending for retry; there is no automatic
switch to another provider/model for this memory role.

Storage, embedding search, result replay, and reminders run locally. When cloud
access is enabled, selected statements go to NVIDIA through Nebius for consolidation,
and messages plus selected context go to the chat model. Privacy pause and cloud-off
settings block both model routes. This is hosted inference; the NVIDIA weights are
not downloaded or run on the user's machine.

## Reproducible evaluation

```bash
venv/bin/python -m blob.evals.private_workflow
venv/bin/python -m blob.evals.private_workflow --live --report /tmp/blob-private-workflow.json
```

The live run sends only synthetic statements and a generated one-page PDF, using
normal API billing. It creates temporary memory, document, result, reminder, skill,
and privacy stores; the installed assistant's personal stores are untouched.
Deterministic local embeddings keep this evaluation independent of embedding
downloads. Text-layer PDF analysis is used; this workflow does not test vision.

The workflow checks:

1. NVIDIA selects an exact study preference for lasting memory and Project Orion
   for middle-term memory, with model provenance attached.
2. Reopening the assistant retains both memories.
3. A PDF study plan follows the remembered preference for three numbered steps
   without repeating that preference in the new request, and covers the PDF topics.
4. The exact completed plan remains available after deleting the original and saved
   PDF copies and reopening the assistant.
5. A natural-language request executes the reminder skill and stores a 15-second
   reminder that survives reopening the assistant.
6. Cloud-off blocks chat and NVIDIA consolidation. Privacy pause blocks a new
   message and new memory writes. The local reminder still fires at its real due time.

The report includes each check, synthetic answers, requested and served model IDs,
completed provider calls, latency, and token usage. Reopen checks reconstruct the
assistant within the evaluation process. Separate daemon tests cover an actual
process restart; logout, reboot, sleep/resume, and network outages still need desktop
validation. The offline run uses scripted model responses and proves no live
provider inference.

## Demo sequence

Use the isolated evaluation for a public recording. To repeat the sequence manually,
the [synthetic study brief](../examples/project_orion/study_brief.pdf) is included
in the repository for use with the installed assistant.

1. Say: “I prefer study plans with exactly three short numbered steps. I am working
   on Project Orion.” Wait for background consolidation, then inspect `/memory
   semantic` and `/memory middle`; `/memory show <tier> <id>` includes model provenance.
2. Restart the backend and submit `study_brief.pdf` with “Using my saved study
   preferences, make a study plan for this Project Orion brief.” Show the three steps.
3. Delete the saved PDF with `/files forget <id>`. Reopen the completed plan using
   `/results show <id>`; show that the answer is retained separately from the source.
4. Say: “Remind me to review my Project Orion study plan in 15 seconds.” Restart the
   backend, turn cloud access off, pause privacy, and show the reminder notification.

Use `/privacy resume` and `/privacy cloud on` afterward to enable cloud assistance again.

Public repository licensing, release packaging, and the submission video remain
separate milestones.
