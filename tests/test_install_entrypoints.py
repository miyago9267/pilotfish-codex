import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerEntrypointTests(unittest.TestCase):
    def test_posix_and_powershell_wrappers_share_the_backend_contract(self) -> None:
        posix = (ROOT / "install" / "install.sh").read_text()
        powershell = (ROOT / "install" / "install.ps1").read_text()
        for wrapper in (posix, powershell):
            self.assertIn("install.py", wrapper)
            self.assertIn("--dry-run", wrapper)
            self.assertIn("--roles-only", wrapper)
            self.assertIn("--ref", wrapper)
            self.assertIn("pilotfish-codex", wrapper)

    def test_powershell_wrapper_has_local_and_remote_paths(self) -> None:
        powershell = (ROOT / "install" / "install.ps1").read_text()
        self.assertIn("$PSScriptRoot", powershell)
        self.assertIn("Invoke-WebRequest", powershell)
        self.assertIn("tar", powershell)
        self.assertIn("finally", powershell)
        self.assertIn("@($RemainingArgs)", powershell)


if __name__ == "__main__":
    unittest.main()
