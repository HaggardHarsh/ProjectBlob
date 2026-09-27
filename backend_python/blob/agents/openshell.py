"""Compatibility entry point for restricted local commands.

This is a command policy, not an operating system sandbox.
"""

import shlex
import subprocess

from blob.skills.command_skill import _allowed


class OpenShellSandbox:
    def execute(self, command: str) -> str:
        argv = shlex.split(command)
        permissions = frozenset({"filesystem.read", "shell.execute", "network.http"})
        if not argv or not _allowed(argv, permissions):
            raise ValueError("Command is not allowed by the local command policy.")
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=10, check=False)
        if result.returncode:
            raise RuntimeError(result.stdout[:4000] or f"Command exited with status {result.returncode}.")
        return result.stdout[:4000]
