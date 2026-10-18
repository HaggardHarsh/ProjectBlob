# Hosted CI verification

All four jobs passed on GitHub's Ubuntu 24.04 runners on 2026-10-18 for commit
`1df3dc4`: [verified workflow run](https://github.com/HaggardHarsh/ProjectBlob/actions/runs/39148230491).

| Job | Verified behavior |
| --- | --- |
| Backend / Python 3.12 | 652 tests passed, 3 explicit environment skips; dependency lock consistency, sdist/wheel build and installed-wheel daemon/resource checks passed. |
| Backend / Python 3.14 | 652 tests passed, 3 explicit environment skips; the same packaging and installed-wheel checks passed. |
| C++ frontend | Native release build and all four CTest checks passed. |
| Ubuntu installer | Stock `/usr/bin/python3` (3.12.3), apt prerequisites, isolated installed candidate, sandboxed Chromium, local embedding warmup, installed-package checks, native CTest, backend regressions, virtual X11 rendering and desktop startup syntax passed. |

The backend skips require the separately installed real Hermes runtime (two tests)
or a supported native Bubblewrap namespace environment (one test). Unsupported
command execution remains fail-closed. Artifacts include backend JUnit/packages
and installer JSON/JUnit/X11 preview; the workflow uses synthetic stores and a
synthetic provider key, with no billed AI calls or personal data.

The [conversation audit](conversation_audit.md) adds a deterministic request and
protocol catalog to both backend jobs and exports `conversation-audit.json`.
Real-model conversation checks use an explicit local `--live` run with synthetic
stores; the CI fixture key cannot test provider behavior.

## Runner differences resolved

Ubuntu's AppArmor policy initially prevented downloaded Playwright Chromium from
creating its sandbox. `deploy/ci/apparmor-playwright` permits user namespaces for
only the runner's cached Chromium executables. The workflow loads this root-owned
profile on its ephemeral runner; Chromium sandboxing remains enabled and the
global namespace restriction remains intact. This follows the
[Chromium AppArmor guidance](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md).

An unusually long Python 3.14 run prompted individual test progress, stalled-thread
dumps and a ten-minute regression-step deadline. Investigation also reproduced
a browser shutdown race: a second close could return while the privacy monitor
was still closing Chromium. A shared cleanup task now survives caller cancellation
and all shutdown callers await it. Both race/cancellation cases pass in both
hosted backend jobs.

The AppArmor profile is a CI fixture for `/home/runner`, not a desktop installation
policy. Real Ubuntu desktops still need an OS policy that permits the configured
Chromium sandbox; setup reports failure rather than disabling the sandbox.
CI does not test real GNOME login, physical reboot, suspend/resume or native Wayland.

## Repository settings

Pushes to `main`, pull requests and manual dispatch run the checks. The workflow's
repository token has only `contents: read`. Publishing credentials separately need
permission to modify workflows; inspecting private runs requires Actions read.

`main` had no branch protection at verification time. CI reports failures but does
not yet block merging. To enforce it, add a branch rule requiring these four
successful checks before merging. That repository policy is separate from the
working workflow and was not changed during validation.
