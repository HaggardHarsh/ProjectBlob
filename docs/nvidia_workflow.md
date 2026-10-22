# NVIDIA memory and a private assistant workflow

Blob uses NVIDIA Nemotron Super for conversation, planning tools, text-only documents,
and saved-work follow-ups. NVIDIA Nemotron Lightning selects persistent personal
memories in the background. Image inputs and rendered PDF pages use GLM because
Super is text-only.

```dotenv
BLOB_MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
BLOB_MEMORY_MODEL_NAME=nvidia/Nemotron-3_5-Lightning
BLOB_VISION_MODEL=zai-org/GLM-5.3-Flash
```

All three use the existing `NEBIUS_API_KEY` and Nebius endpoint. Restart the backend
after changing configuration. The background worker checks for unconsolidated
episodes every 60 seconds. Clear academic declarations are also saved immediately,
so they do not depend on waiting for consolidation.

Nemotron Lightning receives numbered sentences from the user's side of conversation episodes,
with instructions to select lasting facts (`L1`) or expiring project/event facts
(`M2`). Assistant replies are excluded from this request. The backend validates
the codes and saves the original user wording, original source date, source episode,
and `consolidation_model`. It never stores a model-written paraphrase as a grounded
fact. A failed request leaves the episodes pending for retry; there is no automatic
switch to another provider/model for this memory role.

Storage, embedding search, result replay, and reminders run locally. When cloud
access is enabled, selected statements go to Lightning through Nebius for consolidation,
and messages plus selected context go to Super for chat. Selected images and PDF pages
go to GLM for visual analysis. Privacy pause and cloud-off settings block all three
model routes. This is hosted inference; the NVIDIA weights are
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

## Nemotron Super validation

The switch to Super was checked with synthetic data through the real Nebius API:

- [Private workflow](evaluations/nemotron_super_workflow_live.json): 11/11 checks
  passed, covering Lightning consolidation, persistent preferences, document work,
  reminder execution, and privacy controls. The three Super calls took 6.1–7.5
  seconds in this run; these measurements are not a general latency guarantee.
- [Document memory](evaluations/nemotron_super_document_memory_live.json): 6/6
  checks passed with vision disabled, exercising Super directly on extracted PDF
  text. Attachment instructions explicitly make current subject lists the filter
  for personal exam questions even when a branch label conflicts; missing matches
  must not become a list of unrelated exams.
- [Saved work and vision](evaluations/nemotron_super_saved_work_live.json): 4/4
  checks passed using GLM for rendered PDF pages and Super for later text answers.
  The checks include exact local replay after source deletion and a countdown
  calculated from the new clock rather than a previous answer.

## Demo sequence

Use the isolated evaluation for a public recording. The manual demo below uses
Mira, an invented gardener designing an imaginary greenhouse on the Moon, and the
[fictional mission brief](../examples/lunar_greenhouse/mission_brief.pdf). Its
character, project, and dialogue are invented for documentation; this manual
scenario is separate from the recorded automated evaluation above.

1. Say: “Call me Mira. I'm planning a fictional lunar greenhouse. Include a
   materials checklist whenever you make a project plan.” Wait for background
   consolidation, then inspect `/memory
   semantic` and `/memory middle`; `/memory show <tier> <id>` includes model provenance.
2. Restart the backend and submit `mission_brief.pdf` with “Make a greenhouse
   setup plan from this brief.” Check that the plan includes a materials checklist.
3. Delete the saved PDF with `/files forget <id>`. Reopen the completed plan using
   `/results show <id>`; show that the answer is retained separately from the source.
4. Say: “Remind me to review the lunar greenhouse layout in 15 seconds.” Restart the
   backend, turn cloud access off, pause privacy, and show the reminder notification.

Use `/privacy resume` and `/privacy cloud on` afterward to enable cloud assistance again.

Public repository licensing, release packaging, and the submission video remain
separate milestones.
