"""Deadline-limited processes with bounded output, including before truncation."""

import os
import signal
import subprocess
import threading
import time


def run_command(argv, *, timeout=10, max_output_bytes=8000):
    started = time.monotonic()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=os.name == "posix")
    output = bytearray()
    truncated = [False]

    def read():
        try:
            while chunk := process.stdout.read1(4096):
                remaining = max_output_bytes - len(output)
                output.extend(chunk[:remaining])
                truncated[0] |= len(chunk) > remaining
        finally:
            process.stdout.close()

    def kill():
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    reader = threading.Thread(target=read, name="blob-command-output", daemon=True)
    reader.start()
    try:
        process.wait(timeout=max(0.001, timeout - (time.monotonic() - started)))
        reader.join(timeout=max(0, timeout - (time.monotonic() - started)))
        if reader.is_alive():
            raise subprocess.TimeoutExpired(argv, timeout)
    except BaseException:
        kill()
        process.wait()
        reader.join(timeout=1)
        raise
    text = bytes(output).decode("utf-8", errors="replace")
    if truncated[0] or len(text.encode("utf-8")) > max_output_bytes:
        marker = "\n[Additional command output omitted.]"
        text = text.encode("utf-8")[:max_output_bytes - len(marker.encode())].decode("utf-8", errors="ignore") + marker
    return subprocess.CompletedProcess(argv, process.returncode, text)
