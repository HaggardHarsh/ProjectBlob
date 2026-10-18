# Disposable Ubuntu validation

This image is a test fixture, not a Blob distribution. Its `blobtest` account has
passwordless sudo only to exercise native-package setup inside the container.
Do not use the image with personal stores, credentials, home mounts or Docker/
Podman sockets. The build context excludes local environment files and stores.

Use rootless Podman on a Linux host that supports user namespaces. Sandboxed
Chromium needs namespace syscalls allowed by the container seccomp profile; see
[Playwright's container instructions](https://playwright.dev/python/docs/docker).
Do not use `--privileged`, host networking or disable Chromium's sandbox.

On the Fedora validation host, create a copy of the Podman profile with the
three namespace syscalls allowed (profile locations differ by distribution):

```bash
python3 - <<'PY'
import json
from pathlib import Path
profile = json.loads(Path('/usr/share/containers/seccomp.json').read_text())
profile['syscalls'].append({'names': ['clone', 'setns', 'unshare'], 'action': 'SCMP_ACT_ALLOW'})
Path('/tmp/blob-validation-seccomp.json').write_text(json.dumps(profile))
PY
podman build --security-opt seccomp=/tmp/blob-validation-seccomp.json \
  --tag localhost/blob-validation --file deploy/validation/Containerfile.ubuntu .
podman run --detach --name blob-validation --user 0 --systemd=always \
  --security-opt seccomp=/tmp/blob-validation-seccomp.json \
  localhost/blob-validation
podman exec blob-validation loginctl enable-linger blobtest
podman exec blob-validation systemctl start user@1001.service
podman exec blob-validation systemd-run --unit=blob-validation-display --uid=1001 \
  /usr/bin/Xvfb :99 -screen 0 1024x768x24 -nolisten tcp
podman exec --user 1001 -e BLOB_DISPOSABLE_VALIDATION=1 \
  -e XDG_RUNTIME_DIR=/run/user/1001 \
  -e DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus -e DISPLAY=:99 \
  blob-validation python3 tools/validate_desktop_session.py
```

The build prepares one installed candidate and runs its backend/X11 checks.
`validate_desktop_session.py` exercises fresh activation, authenticated chat,
crash restart, saved privacy/reminders and the exact autostart entry point.
After a container restart, recreate the virtual display and user manager as above,
then invoke that script with `--after-container-restart`. This checks container
restart plus the startup entry point, not a physical desktop login or reboot.

For maintenance checks, prepare another candidate inside the same container with
`python3 tools/setup.py --prepare-only`, using the same user/session environment.
Pass its printed directory to `python3 tools/validate_managed_update.py DIRECTORY`
with `BLOB_DISPOSABLE_VALIDATION=1`. The guard deliberately rejects ordinary host
execution. It performs real update, rollback, failed-probe restore, interruption
recovery and uninstall/reinstall against this container's synthetic stores.

`python3 tools/validate_ubuntu_candidate.py --candidate DIRECTORY` verifies the
selected installed wheel and exports JUnit, JSON and PNG evidence in that runtime.
Copy evidence out with `podman cp` before stopping/removing the disposable container.
Do not remove unrelated OpenShell containers or host Blob services.

Nested Bubblewrap cannot mount `/proc` on the tested rootless host. That isolation
test reports an explicit unsupported-environment skip; it must also pass on a
supported native host. Hermes integration tests skip when its separate runtime
is absent. Real GNOME, native Wayland, physical suspend and physical reboot require
a separate PC/VM desktop session; passing these fixtures does not certify them.
