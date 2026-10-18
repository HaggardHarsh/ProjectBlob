# Launch readiness

Target: an Ubuntu/Linux x86-64 desktop beta. This tracker records implementation
and evidence; it is not production certification. Version-pinned dependency
baselines cover CPython 3.12 and 3.14. Hermes/OpenShell remain separate optional
installations. Voice and other operating systems are outside the initial beta.

## Critical work

| Area | Implemented | Remaining release gate |
| --- | --- | --- |
| Tool and retrieval boundaries | Host-derived request permissions, public search queries, checked URLs, literal form values, shell-command constraints, terminal control filtering and known-key redaction. Both agent runtimes use the policy. | Independent adversarial review. These controls do not prove resistance to every prompt injection. See [security review](evals/security_review.md). |
| Factual grounding | General current-information retrieval before inference; actual source reads and checked citations required for live answers. Failed verification returns a clear message. | Repeated live provider/site evaluations. Citations alone do not prove every fact; train inventory remains unsupported without a validated enquiry adapter. |
| Reminders and reconnect | Atomic SQLite outbox, replay on chat reconnect, display-before-ack, repeat coalescing and stale-ack protection. Slow clients cannot block dispatch or shutdown. | Real desktop sleep/wake and extended disconnected sessions. Delivery is at least once; an overlay alone does not provide an OS notification history. |
| Updates and recovery | Separate verified runtime, stopped-store backups, hash/SQLite checks, maintenance admission control, health probe, pre-commit restore, explicit point-in-time rollback, interrupted recovery and uninstall retaining data. | Longer beta use with representative large stores. Editable/manual installs require a reviewed migration to managed runtimes. See [setup](setup.md). |
| Fresh installation and lifecycle | Clean Ubuntu 24.04/Python 3.12 installation, sandboxed Chromium, embedding warmup, installed-wheel checks, virtual X11 overlay, real systemd user activation/crash restart and disposable container restart/startup exercised. | Physical clean Ubuntu PC: GNOME login/logout, reboot, suspend/resume and native Wayland. A container/Xvfb session does not certify these. |
| CI publishing | Workflow published on `main` for Ubuntu 24.04/Python 3.12 and 3.14, package checks, installer and frontend jobs. The first frontend run passed; a runner-scoped AppArmor profile addresses Chromium namespace restrictions. | Full hosted results and required branch checks remain unverified while the corrected workflow runs. |

See [verification evidence](evals/launch_criticals.md) for exact test scope and
limits. The existing workstation installation was not switched during this work.

## Reproduce backend and packaging checks

Use a separate environment on Linux x86-64 with Python 3.12 or 3.14. Substitute
`312`/`3.12` together, or `314`/`3.14` together:

```bash
python3.12 -m venv /tmp/blob-release-check
/tmp/blob-release-check/bin/python -m pip install -r requirements/linux-py312.lock
/tmp/blob-release-check/bin/python -m pip install --no-build-isolation --no-deps -e 'backend_python[dev,web,vision]'
/tmp/blob-release-check/bin/python -m pip check
/tmp/blob-release-check/bin/python tools/lock_dependencies.py --check
/tmp/blob-release-check/bin/python -m playwright install chromium
/tmp/blob-release-check/bin/python -m pytest backend_python/tests -q
/tmp/blob-release-check/bin/python -m build --no-isolation --outdir /tmp/blob-dist backend_python
/tmp/blob-release-check/bin/python -m pip uninstall -y blob-backend
/tmp/blob-release-check/bin/python -m pip install --no-deps /tmp/blob-dist/*.whl
```

From outside `backend_python`, run the checkout's absolute `tools/release_smoke.py`
path with that interpreter and `--source-root /absolute/path/to/ProjectBlob`.
It exercises packaged resources, bundled skill definitions, authenticated IPC,
cloud opt-in, missing-key responses and durable reminders with synthetic stores.
No real provider calls or personal data are needed. Native checks use
`make frontend test-frontend` or a separate CMake build directory.

Locks are version snapshots, not hashed locks, native-library locks or locks for
OCR/Hermes/OpenShell. Regenerate only after resolving and testing on the target
baseline: `python tools/lock_dependencies.py`. Do not snapshot an arbitrary
personal environment.

## Other rollout work

- Measured response deadlines, usage reporting and configurable budgets.
- Distribution artifacts, checksums, dependency license notices and support/bug
  reporting instructions. The source installer is not a signed standalone app.
- Repeated public-site workflows and longer desktop beta sessions.
- Review cancellation, settings and deletion commands with new users. Live-store
  deletion does not erase retained recovery backups.

Release requires the outstanding gates above to be tested or the beta scope to be
explicitly narrowed. Passing regressions is not sufficient to declare final launch.
