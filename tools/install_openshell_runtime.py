"""Install verified official OpenShell 0.1.4 release binaries into .runtime.

No administrator access or global configuration changes. Digests below are
the official v0.1.4 release asset SHA-256 values.
"""

import hashlib
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / ".runtime/openshell"
ASSETS = {
    "x86_64": (
        ("openshell-x86_64-unknown-linux-musl.tar.gz", "2b65178e62e1ece1d90d482555e9f1f98ff0296e058409b33418104b6333df07", "openshell"),
        ("openshell-gateway-x86_64-unknown-linux-gnu.tar.gz", "43f43554bcaabff2a8147444410d1ad0b7f51bdae7589c2d249982bc8b260b91", "openshell-gateway")),
    "aarch64": (
        ("openshell-aarch64-unknown-linux-musl.tar.gz", "1cd6e63597e1947c44a753bf5352f949e8d8d02e344af92ab899b7c111112d95", "openshell"),
        ("openshell-gateway-aarch64-unknown-linux-gnu.tar.gz", "d0f8a2045e613f612a542abe860e497906169c2483093a9bd52e41737df397f0", "openshell-gateway")),
}


def main():
    if sys.platform != "linux" or platform.machine() not in ASSETS:
        raise SystemExit("This local installer supports Linux x86_64/aarch64. See NVIDIA's installation documentation for other platforms.")
    binaries = ROOT / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blob-openshell-install-", dir=ROOT) as directory:
        for asset, expected, executable in ASSETS[platform.machine()]:
            archive = Path(directory) / asset
            print("Downloading", asset, flush=True)
            digest = hashlib.sha256()
            size = 0
            url = "https://github.com/NVIDIA/OpenShell/releases/download/v0.1.4/" + asset
            with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 60 * 1024 * 1024:
                        raise RuntimeError("Release archive exceeds the expected size limit")
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeError("Release checksum mismatch; binary was not installed")
            with tarfile.open(archive) as bundle:
                member = bundle.getmember(executable)
                if not member.isfile() or len(bundle.getmembers()) != 1:
                    raise RuntimeError("Unexpected release archive structure")
                staged = Path(directory) / executable
                with bundle.extractfile(member) as source, staged.open("wb") as target:
                    shutil.copyfileobj(source, target)
                staged.chmod(0o755)
                staged.replace(binaries / executable)
            print("Verified and installed", executable)


if __name__ == "__main__":
    main()
