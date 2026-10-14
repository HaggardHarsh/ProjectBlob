"""Build from a clean pinned Hermes checkout and explicitly selected Blob files.

The temporary build context never includes Blob's .env, memories, credentials,
Git configuration or runtime environments. Run with --prepare-only to inspect it.
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

HERMES_REVISION = "783637e37058dc5a0d5154d4a577160fa2d70a8e"
PROJECT = Path(__file__).resolve().parents[1]


def prepare(context, source):
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != HERMES_REVISION:
        raise ValueError("Hermes checkout must use the pinned revision " + HERMES_REVISION)
    subprocess.run(["git", "-C", str(source), "diff", "--quiet", "HEAD"], check=True)
    paths = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"])
    context.mkdir(parents=True, exist_ok=True)
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode())
        original = source / relative
        if relative.name == ".env" or not original.is_file():
            continue  # Sparse checkout omissions and local secrets are excluded.
        if original.is_symlink() or not original.resolve().is_relative_to(source.resolve()):
            raise ValueError("Build input must not link outside the Hermes checkout: " + str(relative))
        target = context / "hermes" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    shutil.copyfile(PROJECT / "deploy/openshell/Dockerfile", context / "Dockerfile")
    for name in ("hermes_worker.py", "openshell_worker.py"):
        shutil.copyfile(PROJECT / "backend_python/blob/agents" / name, context / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT / ".runtime/hermes")
    parser.add_argument("--engine", choices=("podman", "docker"), default="podman")
    parser.add_argument("--tag", default="localhost/blob-hermes:783637e3")
    parser.add_argument("--prepare-only", type=Path, help="Write a reviewable build context without building")
    args = parser.parse_args()
    if args.prepare_only:
        if args.prepare_only.exists():
            parser.error("Choose a new empty build-context directory")
        prepare(args.prepare_only, args.source)
        print("Prepared build context:", args.prepare_only)
        return
    with tempfile.TemporaryDirectory(prefix="blob-openshell-build-") as directory:
        context = Path(directory)
        prepare(context, args.source)
        subprocess.run([args.engine, "build", "--tag", args.tag, str(context)], check=True)


if __name__ == "__main__":
    main()
