# Initial live runtime comparison

Both engines ran complete terminal conversations through `BlobOrchestrator`
using the configured Nebius Nemotron text model. Hermes used source revision
`783637e37058dc5a0d5154d4a577160fa2d70a8e`, native function calls and Blob's
host-side model/tool bridge. Selected photos used the same MiniCPM vision model
for both engines. All messages, images, stores and reminders were synthetic.

| Check | Classic | Hermes |
| --- | --- | --- |
| Photo identity question stays local | Pass | Pass |
| Draft an email while a photo is selected | Pass | Pass |
| Actual image pixels reach the vision model | Pass | Pass |
| Follow-up retains the selected picture | Pass | Pass |
| Recognition request uses the local camera interface | Pass | Pass |
| Cloud-off blocks inference and permits local camera work | Pass | Pass |
| Create exactly one requested reminder | Fail | Pass |
| List reminders after creating one to verify completion | Fail | Pass |
| Reminder survives backend recreation | Fail | Pass |
| Privacy pause blocks camera and inference | Pass | Pass |

Classic passed 7/10 checks; Hermes passed 10/10. The three different results
come from one multi-step reminder workflow, rather than three independent tasks.
The classic route interprets the later listing request as the primary operation
and blocks creation. The candidate retains each requested action in its
authorization set and uses Hermes's native loop to create once, list, and respond.
The evaluation verifies stored state and actual tool actions, not just the reply.

In this run, email drafting took 2.8 seconds for classic and 4.3 seconds for
Hermes. Hermes's completed reminder workflow took 6.8 seconds. The worker starts
afresh for each conversation turn, adding roughly two seconds of initialization.
This design makes cancellation and removal of its temporary profile straightforward.

These results cover one small conversation set. Camera checks use a deterministic
sensor fixture, not real hardware. Image/camera routing and document storage are
shared code, so their passes establish compatibility rather than a Hermes-specific
improvement. This comparison does not validate OpenShell isolation, browser/email
execution, arbitrary long tasks, model failover or mid-flight privacy interruption.
The latter two are covered by separate deterministic backend tests.

After this comparison, the running service was migrated to Hermes using a persistent
`.env` setting. Ordinary chat and a create-then-list reminder request were checked
through the actual authenticated terminal connection; the temporary reminder was
removed afterward. OpenShell and NemoClaw are not active. Rootless Podman is available;
OpenShell's official system-package installer needs administrator authentication.

See [the synthetic run report](agent_runtime_comparison.json) for responses and
timings, and [runtime setup](../agent_runtime.md) for installation and reproduction.
