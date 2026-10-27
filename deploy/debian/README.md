# Project Blob — Ubuntu test build

This package targets **Ubuntu Desktop 24.04 LTS, Intel/AMD 64-bit**. It contains
the compiled companion, Python runtime dependencies, Playwright Chromium headless
shell and the local embedding model. System libraries are installed by apt.
Internet access and your own Nebius API key are needed for cloud assistance.
OCR, Hermes and OpenShell are optional source-install features, not included here.

## Install

Download the `.deb`, open a terminal in its directory, then run:

```bash
sudo apt install ./projectblob_0.1.0~demo1_amd64.deb
blob-setup
```

Run `blob-setup` as your normal desktop user. Enter your API key privately, or
press Enter to use local commands. The key is saved in `~/.blob/.env`; it is never
part of the download. In Blob Chat, read `/privacy explain`, then enter
`/privacy cloud on` to enable cloud replies. Double-click the companion to chat,
or run `blob-chat`. The application menu also includes Blob Setup and Blob Chat.

`blob-setup` enables login startup for your account. `blob-start` starts it now.
`blob-setup --no-key --no-start` enables startup without prompting or launching.
For manual configuration, use `~/.blob/config.yaml`. Personal stores live in
`~/.blob/`. After editing the key/configuration, restart the services:

```bash
systemctl --user restart blob-backend.service blob-overlay.service
```

The package installs AppArmor rules for its own Chromium and private Bubblewrap
binary. It does not disable AppArmor or Chromium's sandbox. A normal Ubuntu
desktop session with systemd user services is required. Containers may disallow
the namespaces required by Chromium/Bubblewrap even when all libraries exist.

## Existing source installation

Do not run two installations at once. From your original repository, first run
`python3 tools/manage_install.py uninstall`. This preserves personal data and
credentials. Keep the checkout until you have verified the package.
The package reuses default `~/.blob` stores; custom paths must be configured in
`~/.blob/config.yaml`. Enter your key again using `blob-setup`, because a source
checkout's `.env` is not copied. Setup refuses conflicting per-user service files.

## Remove

```bash
systemctl --user stop blob-overlay.service blob-backend.service
sudo apt remove projectblob
```

Your key, conversations, privacy choices and other personal data are preserved.
The per-user autostart entry has `TryExec`, so it is skipped after removal. You may
remove `~/.config/autostart/blob.desktop` yourself. Package upgrades take effect
after restarting the two services or logging out and back in.

## Build from source

On an x86-64 Linux host with Podman (or Docker), run:

```bash
python3 tools/build_deb.py
# or: python3 tools/build_deb.py --engine docker
```

Build artifacts are in `.runtime/debian/dist/`, including a SHA-256 checksum,
Python dependency inventory, and build provenance. The container starts from
Ubuntu 24.04, installs native tools, uses `requirements/linux-py312.lock`, builds
the wheel and C++ overlay, and runs the C++ smoke checks. No credentials or local
data are included. The output is precompiled: installation does not run pip or a
compiler. Building requires internet access and several GB of temporary space.

## Troubleshooting

```bash
systemctl --user status blob-backend.service blob-overlay.service
journalctl --user -u blob-backend -u blob-overlay -n 80 --no-pager
```

A 401 response means the provider rejected the API credentials; rerun
`blob-setup`. Cloud assistance is off by default on fresh profiles. A source
installation working in a VM does not itself validate this packaged build; use
the package's validation report and test it on the target desktop before release.
