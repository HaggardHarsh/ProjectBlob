# Release foundation verification

Historical foundation results. See [launch-critical verification](launch_criticals.md)
for later Ubuntu 24.04 checks and the current CI publishing status.

Verified locally on 2026-10-17, Linux x86-64 / CPython 3.14. These checks do not
establish Windows/macOS support, full desktop lifecycle reliability, or that all
launch blockers are closed. A GitHub Actions workflow was prepared locally;
publication was initially rejected because the saved token lacked workflow
permission. It has since been published in `51b0d28`; hosted results still need
verification. See the current launch evidence linked above.

| Check | Result |
| --- | --- |
| Fresh virtual environment installed from version-pinned dependency closure | Passed; `pip check` found no conflicts and lock verification matched. |
| Backend sdist and wheel rebuilt from that sdist | Passed; packaged defaults, OpenShell policy, protobuf imports and entry points verified outside the checkout. |
| Backend regressions using the installed wheel and isolated test stores | 576 passed, 46 dependency deprecation warnings; includes real Chromium fixtures and local IPC. |
| Installed daemon with no API key | Passed; fresh cloud-off defaults, authenticated IPC, synthetic local reminders, explicit cloud opt-in and clear missing-key response. |
| Overlay configured and built in a fresh directory | Passed; both CTest smoke tests passed. |
| Workflow YAML, matching repository/backend MIT text and clean diff formatting | Passed. |

No real provider requests, personal file analysis or camera capture were needed.
The dependency installation used the package index. Local socket/browser tests
required execution outside the coding environment's restricted socket sandbox.
The default blacklist and personality now live inside the backend package; the
packaged OpenShell policy is compared with its reviewed deployment copy.

The lock pins dependency versions for the release-test profile; it does not pin
native packages or verify distribution hashes. The original draft targeted Ubuntu
22.04; the published workflow targets Ubuntu 24.04. These local results were obtained on the existing development
machine. See [launch readiness](../launch_readiness.md) for remaining gates and
reproduction commands.
