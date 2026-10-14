"""Image entry point; private profiles live only inside the dedicated sandbox."""

import os
import tempfile

from hermes_worker import main


if __name__ == "__main__":
    # The transport already uses env -i; enforce the same rule for manual launches.
    keep = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    os.environ.clear()
    os.environ.update(keep)
    with tempfile.TemporaryDirectory(prefix="blob-hermes-") as profile:
        os.environ["BLOB_WORKER_PROFILE"] = profile
        main()
