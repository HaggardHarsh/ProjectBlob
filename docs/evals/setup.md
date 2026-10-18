# Source installer verification

Historical workstation preparation results. Later clean Ubuntu, managed-update
and recovery evidence is recorded in [launch-critical verification](launch_criticals.md).

Verified on 2026-10-18 on the existing Fedora 44 / Linux x86-64 / CPython 3.14
development machine. The prepare-only path created a fresh isolated virtual
environment and independent frontend build; it did not replace the running
installation. No real provider requests, camera capture or personal-store tests
were used.

| Check | Result |
| --- | --- |
| Native prerequisite check and temporary CMake configure | Passed. |
| Fresh candidate installed with the pinned dependency baseline | Passed; pip consistency and dependency closure checks passed. |
| Installed package resources, real authenticated daemon, local reminders, cloud opt-in and missing-key response | Passed using temporary stores. |
| Chromium launch with an in-memory test page | Passed using the installed browser; Fedora uses Playwright's Ubuntu fallback build. |
| Independent C++ build and CTest | Four tests passed: rendering, attachment IPC, headless startup and animation. |
| Staged user service syntax | Passed `systemd-analyze --user verify`; no units were installed by this check. |
| Full backend suite using the installer-created environment | 595 passed, 46 dependency deprecation warnings. |
| Installer-specific tests after final logic changes | 17 passed; include existing-install refusal, prepare failure, masked key storage, startup/health failure cleanup and exclusive file creation. |
| Existing backend and overlay | Both remained active after verification. |

At the time of this run, automatic Ubuntu/Debian apt installation and live fresh desktop activation were
not run on this personal workstation. A clean Ubuntu desktop install, login/reboot
and compositor checks remain required. The non-3.14 resolver branch has ordering
test coverage but has not yet been exercised in a real Python 3.12 environment.
The optional EasyOCR profile was not installed. These results do not certify an
in-place upgrade or an application package for other operating systems.

See [setup and recovery](../setup.md) for reproduction and current limits.
