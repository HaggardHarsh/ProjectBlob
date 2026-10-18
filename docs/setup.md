# Linux desktop setup

The source installer combines environment creation, Python packages, browser
installation, the C++ build, smoke checks and desktop startup. It targets a fresh
Linux x86-64 desktop with CPython 3.11+. Automatic OS package installation targets
Ubuntu/Debian; other Linux distributions need their native dependencies installed
manually. Python 3.14 has a version-pinned dependency baseline. Other accepted
Python versions resolve dependencies rather than reusing a lock from a different
Python version. Passing local checks does not establish full platform support.

## Install

Run in a terminal inside your graphical desktop, as your ordinary user:

```bash
git clone https://github.com/HaggardHarsh/ProjectBlob.git
cd ProjectBlob
python3 tools/setup.py --install-system-deps
```

The `--install-system-deps` flag explicitly permits `sudo apt-get` for native
development packages, a terminal fallback, and Playwright's Chromium libraries.
Omit it when those are already installed. Setup never runs pip as root or changes
the system Python. Downloads need an internet connection and several GB of free
space. The C++ build uses two jobs by default; use `--jobs 1` on smaller machines.

The installer requires Python 3.11 or newer before it starts; it does not replace
the OS interpreter. On older systems, install a supported Python with venv support
first, then invoke that interpreter explicitly, for example
`python3.12 tools/setup.py --install-system-deps`.

An interactive fresh installation optionally asks for a Nebius API key using a
masked prompt. Press Enter to skip. The key is written only to a new `.env` file
with owner-only permissions. If `NEBIUS_API_KEY` is already set in your terminal,
setup saves it to a new private `.env` so desktop startup can use it too. Existing
`.env` files are left unchanged. You can also copy `.env.example` to `.env` and edit it yourself.
After changing credentials, restart the backend user service.

Once installed, the slime starts automatically at login. Double-click it to open
terminal chat, or launch **Blob Chat** from your applications. Cloud assistance and
automatic screen awareness remain off on fresh profiles. Read `/privacy explain`
and use `/privacy cloud on` when you want cloud chat. Existing saved privacy
settings are preserved. Local commands and reminders work without a provider key.

Web search, page reading, temporary browser interaction, and optional local camera
dependencies are included. Add `--ocr` to install EasyOCR and its larger dependency
set. Screen observation still requires separate user opt-in; GNOME's awareness
extension, Hermes, and OpenShell retain their separate setup instructions. Setup
does not silently change the selected agent runtime or its configuration.

## Checks before startup

Setup first checks native tools and runs a temporary CMake configuration. It then
creates a separate candidate under `.runtime/desktop/releases/` and checks:

- Python dependency consistency and installed package resources.
- A real authenticated local daemon using temporary stores: cloud-off defaults,
  reminders, and the response to a missing provider key. This uses no personal
  stores or provider requests.
- Chromium launching with an in-memory test page and a fresh temporary profile.
- The C++ build and its rendering, attachment IPC, headless and animation tests.
- Rendering desktop startup files before installing them.

Only after these checks succeed does setup install per-user startup files, start
Blob, and verify both user services plus authenticated backend IPC. A failed fresh
activation stops/disables its new units and removes the startup files it created.
The tested candidate remains available for diagnosis. These checks do not exercise
real cloud billing, camera devices, every desktop compositor, or login/reboot.

## Existing installs and recovery

```bash
# Native prerequisite check; no downloads or installation:
python3 tools/setup.py --check

# Separate build and verification; no service/startup changes or API-key prompt:
python3 tools/setup.py --prepare-only
```

The fresh installer refuses an existing checkout `venv`, managed installation,
Blob startup file, or loaded Blob service. It does not upgrade a running install
in place. Use `--prepare-only` to verify a candidate while continuing to use your
existing Blob; a general update/rollback flow remains future work.

Failed preparations leave their candidate directory for inspection and can be
retried. They do not switch the active environment, start services, or rewrite
`.env`, memory, documents, reminders, face samples, or privacy settings. The
`.runtime/desktop/current` link selects a successful managed installation;
`make chat` and `make run-frontend` recognize it. Keep the checkout at its installed
path because desktop services reference its configuration and candidate files.
Do not delete a candidate referenced by `current` or a service.

For startup errors, inspect:

```bash
systemctl --user status blob-backend blob-overlay
journalctl --user -u blob-backend -u blob-overlay -n 80
```

An Ubuntu/Debian machine missing browser libraries should rerun with
`--install-system-deps`. On other distributions, use the missing-library report
and install the corresponding native packages before retrying without that flag.
Existing manual installation and `make desktop-install` remain available; see
[desktop lifecycle](desktop_privacy.md). The source installer is a first step
toward distribution, not a signed standalone application package.
See [verification results](evals/setup.md) for tested paths and remaining checks.
