# Release foundation verification

Verified locally on 2026-10-17, Linux x86-64 / CPython 3.14. These checks do not
establish Windows/macOS support, full desktop lifecycle reliability, or that all
launch blockers are closed. The GitHub Actions workflow has been added but has
not yet run on a hosted runner.

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
native packages or verify distribution hashes. CI exercises an Ubuntu 22.04
baseline, while these local results were obtained on the existing development
machine. See [launch readiness](../launch_readiness.md) for remaining gates and
reproduction commands.
