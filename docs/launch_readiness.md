# Launch readiness

Target: a Linux desktop beta. This is a release-work tracker, not a production
readiness certification. Backend metadata permits Python 3.11+, while the pinned
release-test baseline currently covers Linux x86-64 / CPython 3.14 only. Hermes
and OpenShell require their separately documented installation and verification.

## Implemented release foundations

- `tools/setup.py` combines Linux source installation and isolated backend,
  Chromium and C++ verification before fresh desktop activation. It refuses to
  replace existing installs and rolls back fresh startup files on activation
  failure. Automatic native packages target Ubuntu/Debian; clean-machine testing
  across supported distributions remains required. See [setup](setup.md).
- The C++ overlay has smoother rendering, spring motion, reduced-motion support,
  restored position and size preferences. Chat and privacy/cloud controls use the
  terminal, with no separate frontend panels. See [desktop frontend](desktop_frontend.md).
- New installations start with cloud assistance off. `/privacy explain` describes
  sharing and storage locally; `/privacy cloud on` enables cloud assistance and
  background memory consolidation. Existing saved choices remain intact.
- The backend starts without provider credentials. Missing or example keys produce
  a setup message for cloud conversation requests, without dispatching inference.
- Default configuration files and the reviewed OpenShell policy ship inside the
  backend package. The installed-wheel check verifies the policy matches the
  deployment copy. Existing custom
  files in a source checkout's old `backend_python/data` directory retain priority.
- MIT license text is present in the repository and backend distribution.
- `requirements/linux-py314.lock` pins the installed dependency closure for
  `[dev,web,vision]`, including transitive dependencies and build tools. It excludes
  unrelated local packages and credentials. This is a version snapshot, not a
  hashed lock or a lock for native libraries, OCR, Hermes or OpenShell.
- `.github/workflows/checks.yml` runs backend regressions with real Chromium,
  builds an sdist and then a wheel from it, exercises the installed wheel outside
  the checkout, and builds/tests the overlay on Ubuntu 22.04. It needs no provider
  keys and does not publish or deploy. Repository branch-protection settings must
  separately require these checks. Hosted CI execution still needs verification.

## Reproduce the release checks

Use a **separate** virtual environment on Linux x86-64 / CPython 3.14:

```bash
python3.14 -m venv /tmp/blob-release-check
/tmp/blob-release-check/bin/python -m pip install -r requirements/linux-py314.lock
/tmp/blob-release-check/bin/python -m pip install --no-build-isolation --no-deps -e 'backend_python[dev,web,vision]'
/tmp/blob-release-check/bin/python -m pip check
/tmp/blob-release-check/bin/python tools/lock_dependencies.py --check
/tmp/blob-release-check/bin/python -m playwright install chromium
/tmp/blob-release-check/bin/python -m pytest backend_python/tests -q
/tmp/blob-release-check/bin/python -m build --no-isolation --outdir /tmp/blob-dist backend_python
/tmp/blob-release-check/bin/python -m pip uninstall -y blob-backend
/tmp/blob-release-check/bin/python -m pip install --no-deps /tmp/blob-dist/*.whl
```

Then, from a directory outside the checkout, run its absolute
`tools/release_smoke.py` path using that interpreter and pass
`--source-root /absolute/path/to/ProjectBlob`. The smoke test checks packaged
resources, IPC imports, fresh cloud defaults, preference persistence, and a real
daemon with authenticated local IPC, no API key, and synthetic local reminders.
It uses temporary stores and never enables provider inference. It must be allowed
to create local sockets. Native build checks use `make frontend test-frontend`.

To update dependency versions, resolve them in a clean environment, run the
regressions, then run `python tools/lock_dependencies.py` and review the diff. Do
not regenerate the lock from an arbitrary personal environment or bypass conflicts.

## Remaining rollout gates

| Priority | Work | Evidence required |
| --- | --- | --- |
| P0 | Tool and retrieval security review | Malicious web/PDF content cannot expand permissions or disclose private context through tools; review browser side effects and the pass-through general guardrail methods. |
| P0 | Broader factual grounding | Current-information workflows cite checked sources or report verification failure; no unsupported action-success claims. |
| P0 | Lifecycle and durable reminders | Clean login/reboot/suspend/reconnect tests; notification recovery across crash windows and disconnected clients. |
| P0 | Data upgrades and recovery | Backups, migrations, restore and rollback exercised on previous-version stores; disk-full and interrupted-write behavior verified. |
| P0 | User-facing setup and controls | Validate the source installer on clean supported machines; finish update/uninstall, visible cancellation, settings and data removal flows. |
| P1 | Latency and usage controls | Measured response deadlines, API usage reporting and configurable budgets; clear quota, rate-limit and model-unavailable errors. |
| P1 | Release distribution and support | Native dependencies and artifacts documented, checksums, dependency license notices, update/uninstall path, support and bug-report instructions. |
| P1 | Beta validation | Repeated end-to-end workflows and extended desktop sessions on supported machines; acknowledge untested platforms and websites. |

General guardrail methods are still placeholders; existing privacy, network and
tool controls remain separate mechanisms. A passing regression suite does not
establish resistance to all prompt injection or reliability on arbitrary sites.
Train-seat lookups remain experimental until a supported real enquiry is verified.
Voice and wider platform support are outside the initial beta's release gate.
