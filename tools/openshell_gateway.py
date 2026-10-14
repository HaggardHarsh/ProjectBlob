"""Prepare or run a project-local OpenShell 0.1.4 gateway using rootless Podman.

Uses the official release binaries in .runtime/openshell/bin and mTLS generated
by OpenShell itself. State and CLI registrations stay under .runtime/openshell.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from install_desktop import unit_quote

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / ".runtime/openshell"


def environment():
    # Keep Podman's user socket/session identity, but never provider credentials.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL",
           "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if key in os.environ}
    env.update(XDG_CONFIG_HOME=str(ROOT / "config"), XDG_STATE_HOME=str(ROOT / "state"),
               XDG_DATA_HOME=str(ROOT / "data"))
    return env


def daemon_command():
    tls = ROOT / "tls"
    return [str(ROOT / "bin/openshell-gateway"), "--config", str(ROOT / "gateway.toml"),
        "--name", "blob", "--bind-address", "127.0.0.1", "--port", "17670",
        "--tls-cert", str(tls / "server/tls.crt"), "--tls-key", str(tls / "server/tls.key"),
        "--tls-client-ca", str(tls / "ca.crt"), "--enable-mtls-auth", "true",
        "--enable-operator-auth", "true", "--enable-loopback-service-http", "false",
        "--log-level", "warn"]


def wait_ready():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            result = subprocess.run([str(ROOT / "bin/openshell"), "--gateway", "blob",
                "status", "--output", "json"], env=environment(), stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, timeout=3)
            status = json.loads(result.stdout) if result.returncode == 0 else {}
            if (status.get("status") == "connected" and status.get("version") == "0.1.4" and
                    status.get("authentication", {}).get("status") == "authenticated"):
                print("Blob OpenShell gateway is ready and authenticated.")
                return
        except (subprocess.TimeoutExpired, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Blob OpenShell gateway did not become ready; inspect blob-openshell.service.")


def prepare():
    if not (ROOT / "bin/openshell-gateway").is_file() or not (ROOT / "bin/openshell").is_file():
        raise RuntimeError("Install verified OpenShell v0.1.4 release binaries first; see docs/openshell.md.")
    for name in ("tls", "config", "state", "data"):
        (ROOT / name).mkdir(mode=0o700, parents=True, exist_ok=True)
        (ROOT / name).chmod(0o700)
    env = environment()
    if not (ROOT / "tls/ca.crt").exists():
        subprocess.run([str(ROOT / "bin/openshell-gateway"), "generate-certs",
            "--output-dir", str(ROOT / "tls"), "--server-san", "127.0.0.1",
            "--server-san", "localhost"], env=env, check=True)
    # CLI trust bundle is host-only; supervisor receives only the CA.
    bundle = ROOT / "config/openshell/gateways/blob/mtls"
    bundle.mkdir(mode=0o700, parents=True, exist_ok=True)
    for source, target in (("ca.crt", "ca.crt"), ("client/tls.crt", "tls.crt"),
                           ("client/tls.key", "tls.key")):
        shutil.copyfile(ROOT / "tls" / source, bundle / target)
        (bundle / target).chmod(0o600)
    for path in (ROOT / "tls").rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    config = ("[openshell]\nversion = 2\n\n[openshell.gateway]\n"
        'compute_driver = "podman"\n'
        f"guest_tls_ca = {json.dumps(str(ROOT / 'tls/ca.crt'))}\n\n"
        '[openshell.drivers.podman]\nimage_pull_policy = "if_not_present"\n'
        'health_check_interval_secs = 10\nstop_timeout_secs = 5\n\n'
        '[openshell.gateway.gateway_jwt]\n'
        f"signing_key_path = {json.dumps(str(ROOT / 'tls/jwt/signing.pem'))}\n"
        f"public_key_path = {json.dumps(str(ROOT / 'tls/jwt/public.pem'))}\n"
        f"kid_path = {json.dumps(str(ROOT / 'tls/jwt/kid'))}\n"
        'gateway_id = "blob-local"\n')
    (ROOT / "gateway.toml").write_text(config)
    subprocess.run([str(ROOT / "bin/openshell-gateway"), "config", "preflight",
        "--", *daemon_command()[1:]], env=env, check=True)


def stage_service():
    interpreter = PROJECT / "venv/bin/python"
    if not interpreter.is_file():
        interpreter = Path(sys.executable).absolute()
    if any(char in str(PROJECT) + str(interpreter) for char in "\n\r"):
        raise ValueError("Service paths cannot contain newlines")
    unit = f"""[Unit]
Description=Project Blob OpenShell gateway
Requires=podman.socket
After=podman.socket

[Service]
Type=simple
WorkingDirectory={str(PROJECT).replace('%', '%%')}
ExecStart={unit_quote(interpreter).replace('$', '$$')} {unit_quote(PROJECT / 'tools/openshell_gateway.py').replace('$', '$$')} run
ExecStartPost={unit_quote(interpreter).replace('$', '$$')} {unit_quote(PROJECT / 'tools/openshell_gateway.py').replace('$', '$$')} wait-ready
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
UMask=0077

[Install]
WantedBy=default.target
"""
    target = ROOT / "blob-openshell.service"
    target.write_text(unit)
    target.chmod(0o600)
    return target


def install_service():
    staged = stage_service()
    target = Path.home() / ".config/systemd/user/blob-openshell.service"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(staged, target)
    target.chmod(0o600)
    dropin = target.parent / "blob-backend.service.d/openshell.conf"
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text("[Unit]\nWants=blob-openshell.service\nAfter=blob-openshell.service\n")
    dropin.chmod(0o600)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "blob-openshell.service"], check=True)
    print("Installed and started blob-openshell.service")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "register", "status", "cli", "stage-service", "install-service", "wait-ready"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="Arguments forwarded to the project-local CLI")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "stage-service":
        print(stage_service())
    elif args.command == "install-service":
        install_service()
    elif args.command == "wait-ready":
        wait_ready()
    elif args.command == "run":
        if not (ROOT / "gateway.toml").is_file():
            parser.error("Run prepare first")
        os.execve(daemon_command()[0], daemon_command(), environment())
    elif args.command == "register":
        subprocess.run([str(ROOT / "bin/openshell"), "gateway", "add",
            "https://127.0.0.1:17670", "--local", "--name", "blob"],
            env=environment(), check=True)
    elif args.command == "cli":
        subprocess.run([str(ROOT / "bin/openshell"), "--gateway", "blob", *args.arguments],
            env=environment(), check=True)
    else:
        subprocess.run([str(ROOT / "bin/openshell"), "--gateway", "blob", "status",
            "--output", "json"], env=environment(), check=True)


if __name__ == "__main__":
    main()
