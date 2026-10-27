"""Regression checks for package setup, using only temporary user profiles."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("package_launcher", Path(__file__).with_name("launcher.py"))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.env = patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "config")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.state = self.home / ".blob"
        self.state.mkdir()

    def test_repeat_setup_preserves_privacy_and_credentials(self):
        secret = self.state / ".env"
        secret.write_text("NEBIUS_API_KEY=synthetic-test-value\n")
        privacy = self.state / "privacy.json"
        privacy.write_text('{"cloud_enabled":false}')
        with patch.object(launcher, "systemctl") as systemctl:
            for _ in range(2):
                launcher.setup(self.state, ["--no-key", "--no-start"])
        systemctl.assert_not_called()
        self.assertEqual(secret.read_text(), "NEBIUS_API_KEY=synthetic-test-value\n")
        self.assertEqual(privacy.read_text(), '{"cloud_enabled":false}')
        self.assertIn("TryExec=/usr/bin/blob-start", (self.home / "config/autostart/blob.desktop").read_text())

    def test_source_conflict_does_not_modify_any_settings(self):
        unit = self.home / "config/systemd/user/blob-backend.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("existing source unit")
        with self.assertRaisesRegex(RuntimeError, "existing source installation"):
            launcher.setup(self.state, ["--no-key", "--no-start"])
        self.assertFalse((self.home / "config/autostart/blob.desktop").exists())
        self.assertEqual(unit.read_text(), "existing source unit")

    def test_dangling_unit_symlink_is_also_a_conflict(self):
        unit = self.home / "config/systemd/user/blob-overlay.service"
        unit.parent.mkdir(parents=True)
        unit.symlink_to(self.home / "missing-source")
        with self.assertRaisesRegex(RuntimeError, "existing source installation"):
            launcher.check_source_install()

    def test_root_is_rejected_before_profile_creation(self):
        with patch.object(os, "geteuid", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "without sudo"):
                launcher.environment()
        self.assertFalse((self.home / ".cache").exists())

    def test_key_setup_uses_private_permissions_and_preserves_other_settings(self):
        secret = self.state / ".env"
        secret.write_text("BLOB_CAMERA_ENABLED=0\nNEBIUS_API_KEY=old-test-value\n")
        secret.chmod(0o644)
        with patch.object(launcher.getpass, "getpass", return_value="new-synthetic-test-value"):
            launcher.setup(self.state, ["--no-start"])
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        from dotenv import dotenv_values
        self.assertEqual(dotenv_values(secret)["NEBIUS_API_KEY"], "new-synthetic-test-value")
        self.assertEqual(dotenv_values(secret)["BLOB_CAMERA_ENABLED"], "0")

    def test_secret_symlink_is_not_overwritten(self):
        target = self.home / "other-config"
        target.write_text("keep me")
        (self.state / ".env").symlink_to(target)
        with patch.object(launcher.getpass, "getpass", return_value="synthetic-test-value"):
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                launcher.setup(self.state, ["--no-start"])
        self.assertEqual(target.read_text(), "keep me")


if __name__ == "__main__":
    unittest.main()
