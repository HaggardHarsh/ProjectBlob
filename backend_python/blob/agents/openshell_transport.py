"""OpenShell 0.1.4 stdio transport; one dedicated sandbox per warm worker.

The host keeps inference, credentials, tool execution and desktop hardware.
Never reconnect or replay a bridge after a disconnect. Killing the local CLI
alone is insufficient: stop the remote sandbox and wait for confirmation.
"""

import asyncio
import os
from pathlib import Path
import shutil
import signal
import uuid
import yaml

from blob.agents.hermes import AgentRuntimeError, MAX_FRAME_BYTES


class OpenShellWorkerTransport:
    def __init__(self, config):
        self.config = config
        self.name = None
        self.active = False
        self.cleanup_status = None

    def command(self, *args):
        cli = shutil.which(str(Path(self.config.openshell_cli).expanduser()))
        if not cli:
            raise AgentRuntimeError("OpenShell CLI is missing. See docs/openshell.md; local execution was not used.")
        return [cli, "--color", "never", "--gateway", self.config.openshell_gateway,
                "--workspace", self.config.openshell_workspace, *args]

    def environment(self):
        # TLS/CLI registration stays on the host. No provider environment is inherited.
        env = {key: os.environ[key] for key in
               ("PATH", "HOME", "LANG", "LC_ALL", "XDG_CONFIG_HOME", "XDG_STATE_HOME")
               if key in os.environ}
        if self.config.openshell_config_dir:
            env["XDG_CONFIG_HOME"] = str(Path(self.config.openshell_config_dir).expanduser().resolve())
        env["NO_COLOR"] = "1"
        return env

    async def _control(self, *args, timeout=30):
        """Bound control output and kill its CLI process on timeout/cancellation."""
        process = await asyncio.create_subprocess_exec(
            *self.command(*args), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=self.environment(), start_new_session=os.name == "posix")
        try:
            async with asyncio.timeout(timeout):
                output = bytearray()
                while chunk := await process.stdout.read(4096):
                    if len(output) + len(chunk) > 65536:
                        raise AgentRuntimeError("OpenShell control output exceeded its size limit.")
                    output.extend(chunk)
                await process.wait()
                if process.returncode:
                    raise AgentRuntimeError("OpenShell control request failed. Inspect the gateway and sandbox with blob-agent doctor.")
                return output.decode("utf-8", errors="replace")
        finally:
            if process.returncode is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

    async def launch(self):
        if self.name is not None:
            raise AgentRuntimeError("Previous OpenShell sandbox cleanup is pending; close it before starting another worker.")
        policy = Path(self.config.openshell_policy_path).expanduser()
        if not policy.is_file():
            raise AgentRuntimeError("Blob's OpenShell policy is missing. See docs/openshell.md.")
        self.command()  # Validate the host CLI before recording a possibly created sandbox.
        try:
            rules = yaml.safe_load(policy.read_text())
            if (rules.get("network_policies") != {} or
                    rules.get("landlock", {}).get("compatibility") != "hard_requirement" or
                    rules.get("filesystem_policy", {}).get("read_write") != ["/tmp"] or
                    rules.get("filesystem_policy", {}).get("include_workdir") is not False):
                raise ValueError("Unexpected worker permissions")
        except (ValueError, AttributeError, OSError, yaml.YAMLError) as exc:
            raise AgentRuntimeError("Blob's OpenShell worker requires denied network egress, enforced Landlock and writes only to /tmp.") from exc
        # Unique, owned name is set before creation: cancelled creates also require cleanup.
        # OpenShell 0.1.4 sandbox names have a 19-character limit.
        self.name = "blob-h-" + uuid.uuid4().hex[:12]
        self.cleanup_status = None
        await self._control("sandbox", "create", "--name", self.name,
            "--from", self.config.openshell_image, "--policy", str(policy.resolve()),
            "--detach", "--no-tty", "--no-auto-providers", "--restart-policy", "never",
            "--cpu", "1", "--memory", "1Gi", "--label", "app=blob-hermes",
            "--", "/usr/bin/sleep", "infinity", timeout=self.config.agent_timeout_seconds)
        self.active = True
        # No shell startup files, PTY conversion, provider credentials or remote retries.
        return await asyncio.create_subprocess_exec(
            *self.command("sandbox", "exec", "--name", self.name, "--no-tty",
                "--no-login-shell", "--timeout", "0", "--",
                "/usr/bin/env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
                "/usr/local/bin/python", "-u", "/opt/blob/openshell_worker.py",
                "--source", "/opt/hermes"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=self.environment(),
            start_new_session=os.name == "posix", limit=MAX_FRAME_BYTES)

    async def close(self):
        if self.name is None:
            return
        name = self.name
        stopped = False
        try:
            try:
                await self._control("sandbox", "stop", name)
                stopped = True
                self.active = False
            except (AgentRuntimeError, TimeoutError):
                # Creation may have failed or the sandbox may already be absent.
                pass
            deleted = await self._control("sandbox", "delete", name)
            removed = (f"Deleted sandbox {name}" in deleted or
                       f"Sandbox {name} already deleted" in deleted)
            if not stopped and not removed:
                raise AgentRuntimeError("OpenShell could not confirm the remote worker stopped.")
            self.cleanup_status = "deleted" if removed else "stopped; deletion pending"
            self.active = False
            self.name = None
        except (AgentRuntimeError, TimeoutError) as exc:
            self.cleanup_status = "pending"
            raise AgentRuntimeError(f"OpenShell cleanup is pending for {name}. Inspect and stop that sandbox before retrying.") from exc
