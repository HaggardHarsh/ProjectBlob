"""Measure real Hermes overhead with synthetic replies and no cloud inference."""

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import time
from types import SimpleNamespace

from openai.types.chat import ChatCompletion

from blob.agents.hermes import HermesAgentWrapper
from blob.config import BlobConfig


async def measure(turns):
    async def completion(**kwargs):
        return ChatCompletion.model_validate({"id": "latency", "object": "chat.completion",
            "created": 0, "model": "offline", "choices": [{"index": 0,
            "message": {"role": "assistant", "content": "Ready."}, "finish_reason": "stop"}]})

    async def tool(*args):
        raise AssertionError("Latency measurement must not execute tools")

    async def event(*args):
        pass

    runtime = HermesAgentWrapper(BlobConfig.load(), SimpleNamespace(_create=completion))
    report = {"scope": "real Hermes; synthetic local model; no cloud inference", "turns": turns}
    try:
        for mode in ("cold", "warm"):
            await runtime.close()
            if mode == "warm":
                started = time.monotonic()
                await runtime.start()
                report["preload_ms"] = round((time.monotonic() - started) * 1000)
            samples = []
            for _ in range(turns):
                if mode == "cold":
                    await runtime.close()
                answer = await runtime.run([{"role": "user", "content": "Say Ready."}],
                    "Reply briefly.", [], tool, event)
                assert answer == "Ready."
                samples.append(dict(runtime.last_run))
            report[mode] = {"median_ms": statistics.median(item["duration_ms"] for item in samples),
                            "runs": samples}
        report["saved_median_ms"] = report["cold"]["median_ms"] - report["warm"]["median_ms"]
        return report
    finally:
        await runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=5)
    parser.add_argument("--output")
    args = parser.parse_args()
    if not 1 <= args.turns <= 30:
        parser.error("--turns must be between 1 and 30")
    report = asyncio.run(measure(args.turns))
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
