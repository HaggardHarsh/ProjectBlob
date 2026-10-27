"""Build a precompiled Ubuntu 24.04 amd64 release in an isolated container."""

import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("podman", "docker"), default="podman")
    parser.add_argument("--base-image", default="docker.io/library/ubuntu:24.04")
    parser.add_argument("--version", default="0.1.0~demo1")
    args = parser.parse_args()
    output = ROOT / ".runtime/debian/dist"
    source = ROOT / ".runtime/debian/source"
    output.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.rmtree(source)
    source.mkdir(parents=True)
    # Only tracked release inputs plus the new packaging files. Never copy .env,
    # the working runtime, user stores, or unrelated untracked documents.
    paths = subprocess.check_output(["git", "ls-files", "-z", "backend_python", "frontend_cpp",
        "proto", "requirements", "skills", "deploy/openshell/policy.yaml", "LICENSE",
        "tools/release_smoke.py"], cwd=ROOT).decode().split("\0")
    paths += [str(path.relative_to(ROOT)) for path in (ROOT / "deploy/debian").rglob("*")
              if path.is_file() and "__pycache__" not in path.parts]
    for relative in filter(None, paths):
        path = ROOT / relative
        if path.name == ".env" or path.suffix in {".pyc", ".db", ".sqlite3"}:
            raise RuntimeError("Unexpected private/generated build input: " + relative)
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (source / "SOURCE_REVISION").write_text(revision + "\n")
    command = [args.engine, "run", "--rm", "--user", "0", "--platform", "linux/amd64",
               "--volume", f"{source}:/src:ro,Z", "--volume", f"{output}:/out:Z",
               "--env", "DEBIAN_FRONTEND=noninteractive", args.base_image,
               "bash", "-ec", "apt-get update; apt-get install -y --no-install-recommends python3; "
               'exec python3 /src/deploy/debian/build.py "$1"', "build", args.version]
    subprocess.run(command, check=True)
    print("Release artifacts:", output)


if __name__ == "__main__":
    main()
