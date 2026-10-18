# Launch-critical verification

Verified on 2026-10-18 using synthetic stores. The existing workstation's Blob
backend, overlay, personal data and selected agent runtime were not replaced.
Machine-readable results: [launch_criticals.json](launch_criticals.json).

| Check | Result |
| --- | --- |
| Final installed wheel on Fedora 44 / CPython 3.14 | **631 passed**, zero skips/failures; 46 dependency deprecation warnings. |
| Final installed wheel on clean Ubuntu 24.04 / stock CPython 3.12.3 | **628 passed, 3 skipped**, zero failures; 45 dependency deprecation warnings. |
| Updated protobuf and independent C++ builds | Four CTest tests passed on both hosts: rendering, attachment IPC, headless startup, animation. |
| sdist and wheel rebuilt from the sdist | Passed. Packaged YAML defaults, reviewed OpenShell policy and all three bundled skill files verified. |
| Installed-wheel daemon smoke outside the source package | Passed: authenticated local IPC, cloud-off default, missing-key response, synthetic reminders, unread-delivery replay and acknowledgement. No provider requests. |
| Clean Ubuntu source preparation | Passed: apt prerequisites, 3.12 lock, pip consistency, local embedding download/warmup, sandboxed Chromium, native build and staged startup files. |
| Ubuntu desktop fixture | Passed: real systemd user services, virtual X11 overlay, authenticated chat, backend SIGKILL/restart, privacy/reminder persistence and exact autostart entry point. |
| Disposable Ubuntu container restart | Passed: manager/display recreation and startup entry point preserved privacy/reminder state. |
| Real managed update from the earlier installed runtime | Passed: stopped-store backup, packaged-runtime replacement, readiness commit and clear maintenance state. |
| Real previous-runtime rollback | Passed: old code/data restored, later reminder removed from the restored state, newer safety backup retained. |
| Failed candidate and interrupted maintenance | Passed: injected post-startup probe failure and interrupted transaction both restored checked data and real services. |
| Uninstall/reinstall | Passed: startup removed; synthetic stores, credentials/configuration state, runtimes and backups retained; reactivation reconnected to the same stores. |
| Failure regressions | Passed: legacy SQLite migration, crash after outbox commit, disconnect replay, unauthenticated ack rejection, stale repeat ack, disk-full transaction rollback, snapshot tampering and copy-failure preservation. |

The Ubuntu skips were two tests requiring the separately installed real Hermes
runtime and one namespace test: nested Bubblewrap cannot mount `/proc` on this
rootless container host. Unsupported tools remain fail-closed. All three tests
ran and passed in the supported workstation environment. The Python 3.14 wheel
used an isolated package installation with the already verified dependency
environment; the clean Ubuntu candidate installed its own dependency closure.

The clean Ubuntu fixtures found and fixed a Python 3.12 OpenShell subprocess
cleanup hang, missing packaged skill definitions, cold embedding download delay,
and the installer's earlier browser smoke configuration differing from the real
sandboxed browser. These fixes are covered by the checks above.

## Reproduction

- Backend/package commands: [launch tracker](../launch_readiness.md).
- User installation/update/recovery commands: [setup](../setup.md).
- Disposable Ubuntu image and guarded session/maintenance helpers:
  [validation instructions](../../deploy/validation/README.md).
- Tool boundaries and residual adversarial risks: [security review](security_review.md).

The helpers export JUnit, validation JSON, managed-update JSON and an X11 preview
in the candidate directory. The fixtures use no real provider billing, personal
documents, camera capture or public ticket enquiry submissions.

## Still required before broader rollout

Use a separate physical Ubuntu desktop or full desktop VM for GNOME login/logout,
physical reboot, suspend/resume and native Wayland. Container/Xvfb evidence is
not evidence for those compositor/session behaviors. Exercise longer sessions,
larger representative stores and repeated real public-site/provider workflows.

Train inventory needs a validated site-specific enquiry adapter. The generic
browser can read and interact with supported public GET-based pages, but final
seat availability is deliberately reported as unverified. POST enquiry forms,
login and CAPTCHA require manual handling.

An independent adversarial review remains desirable before broader distribution;
the local review and synthetic fixtures do not prove semantic accuracy or immunity
to every injection. Native distribution artifacts, license notices and measured
latency/usage budgets remain separate rollout work.

The workflow was subsequently published on `main` in `51b0d28`. All four hosted
jobs passed for `1df3dc4`: Python 3.12/3.14 (652 passed, 3 environment skips each),
packaging, the C++ frontend and the stock Ubuntu installer. The earlier credential
and runner sandbox blockers are resolved. See [hosted CI evidence](ci.md) for the
run link, scoped AppArmor fixture and browser cleanup regression. Branch protection
requiring successful checks on `main` remains a separate repository setting.
