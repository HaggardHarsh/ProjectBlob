# OpenShell integration verification

Verified on 2026-10-14 with OpenShell 0.1.4, rootless Podman 5.8.7, and Hermes
revision `783637e37058dc5a0d5154d4a577160fa2d70a8e` on Fedora 44.

[The real runtime evaluation](openshell.json) passed **13/13** checks. It used
synthetic local inference and a synthetic host tool, without cloud calls,
personal data, camera access or screen capture. Checks covered preloading,
non-root execution, absent provider keys, read-only code, explicit network-denial
errors, no new privileges, seccomp, native host tool mediation, replies, worker
reuse, per-turn history and permissions, and cancellation with confirmed remote
shutdown. The final cancellation receipt reports deletion completed.

Two warm turns took 171 ms (two synthetic model calls and one synthetic tool)
and 118 ms (one synthetic model call). These are integration overhead samples;
they do not measure Nebius latency or model quality.

The targeted runtime, configuration, privacy and IPC regression suite passed
**54 tests**. The user service unit passed `systemd-analyze --user verify`.
The development installation was then switched to OpenShell and its backend
restarted. Its authenticated local `/agent` status confirmed `transport:
openshell`, `worker_ready: true`, and `sandbox_active: true`.

The persistent gateway uses local mTLS, explicit gateway launch-signing keys,
and an authenticated readiness gate before the backend starts. The installed
`blob-openshell.service` requires the Podman user socket. Diagnostic and
evaluation sandboxes were removed; the active backend owns its own sandbox.

Reproduce the evaluation before activation with:

```bash
venv/bin/python -m blob.evals.openshell --local-gateway \
  --output /tmp/blob-openshell-eval.json
```

See [setup and rollback](../openshell.md). The local transport remains the
configuration default for fresh installations.
