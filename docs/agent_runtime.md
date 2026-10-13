# Hermes runtime

Blob can use the real Hermes `AIAgent` conversation loop for ordinary terminal
chat and built-in task tools. The running development installation selects
`hermes` persistently in `.env`. Fresh installations retain the `classic`
configuration default until the separate Hermes runtime is installed and selected.
There is no additional chat window.

The first integration uses a separate Python worker and native function calls.
The worker gets no provider API key. Every model request goes through Blob's
configured Nebius client and privacy controls. Every tool request goes through
Blob's validated skill registry. Camera and fresh screen capture remain explicit
local operations; photo/PDF descriptions retain Blob's existing vision pipeline.
This phase does not replace attachment selection, document memory or local camera
intent handling. Image tests therefore check regressions in a shared pipeline,
not an improvement attributable to Hermes.

The integration exposes weather, read-only shell commands, Git status and reminders;
file search is exposed for file-search requests. It does not enable Hermes's
default shell, browser, plugins, delegation, scheduled jobs or memory tools.
Reminder changes require the current user's request. A successful creation cannot
be repeated in the same turn. Blob retains its existing reminder store and memory.

Execution events drive desktop emotions. Worker profiles are temporary and owned
by Blob, so they are removed after completion, failure, timeout or cancellation.
Run receipts contain tool names, success flags, model-call count and duration;
they contain no tool arguments, file contents or conversation text.

## Installation

Hermes is a separate runtime, not a dependency in Blob's virtual environment.
The verified source revision is `783637e37058dc5a0d5154d4a577160fa2d70a8e`
from <https://github.com/NousResearch/hermes-agent>. This revision uses Python 3.14.

From the repository root, prepare a sparse source checkout and separate environment:

```bash
git clone --filter=blob:none --sparse https://github.com/NousResearch/hermes-agent.git .runtime/hermes
git -C .runtime/hermes checkout 783637e37058dc5a0d5154d4a577160fa2d70a8e
git -C .runtime/hermes sparse-checkout set agent tools hermes_cli gateway plugins acp_adapter pm scripts cron hermes_platform providers locales
python3.14 -m venv .runtime/hermes-venv
.runtime/hermes-venv/bin/python -m pip install -e .runtime/hermes
```

Project checkouts find `.runtime/hermes` and its interpreter automatically.
For a different installation location, set the absolute paths in `.env` (these
path settings work for doctor and evaluations without switching the backend):

```dotenv
BLOB_HERMES_SOURCE=/absolute/path/to/ProjectBlob/.runtime/hermes
BLOB_HERMES_PYTHON=/absolute/path/to/ProjectBlob/.runtime/hermes-venv/bin/python
```

Check installation with no cloud call:

```bash
venv/bin/python -m blob.agents.cli doctor --probe
```

This installation already selects `BLOB_AGENT_RUNTIME=hermes` and has restarted
the backend. For another installation, choose that setting and restart the backend.
Use `/agent` in terminal chat to see the selected runtime and last run receipt.
Rollback by selecting `BLOB_AGENT_RUNTIME=classic` and restarting. A missing or
failed Hermes runtime produces an explicit error; it never silently retries a
task through the classic engine. Do not automatically retry external actions
after a timeout; inspect their completed tool receipts first.

## Workflow comparison

```bash
venv/bin/python -m blob.evals.agent_runtime --live --output /tmp/blob-runtime-comparison.json
```

Both runtimes receive the same synthetic email, image and reminder workflows.
The [initial live comparison](evals/agent_runtime_comparison.md) passed 10/10
checks for Hermes and 7/10 for classic; the improvement covers one multi-step
reminder workflow and does not establish general agent reliability.
The evaluation uses temporary local stores and a deterministic camera fixture;
it does not open your webcam or send personal memories or images. `--live` sends
synthetic messages and a generated red/blue image to your configured provider.
Both candidates use MiniCPM for the shared vision checks to separate agent-loop
behavior from GLM timeout variability. Without `--live`, the real Hermes core
runs with synthetic model replies; that validates integration, not language-model
quality. Unit tests separately cover privacy interruption, unauthorized tools,
context limits, duplicate reminders and cancellation of child processes.

The unit-test fixtures select classic explicitly for their existing mocked model
responses, independently of the live installation's `.env` setting. Hermes tests
run the real worker with structured synthetic responses. The live workflow command
above selects each runtime explicitly and uses real model responses.

## OpenShell and NemoClaw deployment

The active Hermes integration uses a local process boundary. It is **not** running inside
NVIDIA OpenShell or NemoClaw. `doctor` reports those separately and never claims
an active kernel sandbox just because an executable exists.

The existing `OpenShellSandbox` compatibility class is a command allowlist; it
does not integrate NVIDIA OpenShell. Command skills already use Blob's existing
Bubblewrap isolation. NVIDIA OpenShell is installed through its official runtime
installer, not the unrelated `openshell` Python extra previously listed here.

For the next deployment stage, use [NemoClaw's Hermes guide](https://docs.nvidia.com/nemoclaw/user-guide/hermes/home)
and [OpenShell's architecture](https://docs.nvidia.com/openshell/about/architecture).
Provision the worker's pinned source/interpreter inside a sandbox, leave camera
and screen hardware in the host integration, and test stop/disconnect behavior
before switching to that transport. Keep native Hermes shell/browser tools off
until network and filesystem policies, action permissions and run receipts are
verified end to end. OpenShell controls allowed destinations; an allowed cloud
image request still sends image content outside the computer.

On the development host, rootless Podman works. Docker is installed but its daemon
socket is absent; starting it with noninteractive sudo requires a password. The
OpenShell/NemoClaw CLIs are absent. OpenShell's official Linux installer uses system
Debian/RPM packages, requiring administrator authentication. The Hermes adapter
can be evaluated independently while that deployment prerequisite is resolved.

Upstream integration references:
[programmatic interfaces](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration)
and [agent architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture).
