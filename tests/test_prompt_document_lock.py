from __future__ import annotations

import json
import sys
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))

from validate_prompt_lock import (  # noqa: E402
    PromptLockError,
    check_change_budget,
    load_lock,
    validate_lock,
)


class PromptDocumentLockTests(unittest.TestCase):
    @contextmanager
    def _git_repo_with_current_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = load_lock(ROOT)
            for surface in lock["surfaces"]:
                source = ROOT / surface["path"]
                destination = root / surface["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            manifest = root / "docs" / "specs" / "prompt-document-lock" / "LOCK.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / manifest.relative_to(root), manifest)
            shutil.copyfile(ROOT / "VERSION", root / "VERSION")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "prompt-lock@test.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Prompt Lock Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "test: establish prompt lock"], cwd=root, check=True)
            yield root

    def test_current_prompt_surfaces_pass_the_lock(self) -> None:
        report = validate_lock(ROOT, base_ref="HEAD")

        self.assertEqual(report["status"], "ok")
        self.assertGreaterEqual(report["surface_count"], 10)
        self.assertEqual(report["base_diff"], "checked")

    def test_manifest_covers_the_prompt_and_description_surfaces(self) -> None:
        lock = load_lock(ROOT)
        paths = {surface["path"] for surface in lock["surfaces"]}

        self.assertIn("templates/agents-md.bootstrap.md", paths)
        self.assertIn("templates/agents-md.orchestration.md", paths)
        self.assertIn(
            "plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/references/orchestration-policy.md",
            paths,
        )
        self.assertIn("plugin/plugins/pilotfish-codex/skills/pilotfish-orchestration/SKILL.md", paths)
        self.assertIn("INSTALL_PROMPT.md", paths)

    def test_small_text_change_stays_within_a_surface_budget(self) -> None:
        surface = {
            "max_changed_lines": 2,
            "max_changed_characters": 80,
            "max_change_ratio": 0.5,
        }

        metrics = check_change_budget(surface, "one\ntwo\n", "one\ntoo\n")

        self.assertEqual(metrics["changed_lines"], 2)
        self.assertEqual(metrics["changed_characters"], 6)

    def test_large_prompt_rewrite_is_rejected(self) -> None:
        surface = {
            "max_changed_lines": 2,
            "max_changed_characters": 20,
            "max_change_ratio": 0.2,
        }

        with self.assertRaisesRegex(PromptLockError, "change budget"):
            check_change_budget(
                surface,
                "keep this contract\n" * 8,
                "replace this contract\n" * 8,
            )

    def test_git_base_diff_budget_is_enforced(self) -> None:
        with self._git_repo_with_current_lock() as root:
            scout = root / "templates" / "agents" / "scout.toml"
            scout.write_text(scout.read_text(encoding="utf-8") + "bounded\n" * 9, encoding="utf-8")

            with self.assertRaisesRegex(PromptLockError, "change budget"):
                validate_lock(root, base_ref="HEAD")

    def test_protected_prompt_change_requires_a_version_update(self) -> None:
        with self._git_repo_with_current_lock() as root:
            scout = root / "templates" / "agents" / "scout.toml"
            scout.write_text(
                scout.read_text(encoding="utf-8").replace("fast, read-only", "quick, read-only"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(PromptLockError, "VERSION update"):
                validate_lock(root, base_ref="HEAD")

    def test_manifest_declares_immutable_update_protocol(self) -> None:
        lock = load_lock(ROOT)

        self.assertEqual(lock["schema_version"], 1)
        self.assertEqual(lock["status"], "active")
        self.assertTrue(lock["manifest_immutable"])
        self.assertIn("--allow-lock-update", lock["update_protocol"])
        self.assertEqual(lock["version_gate"]["path"], "VERSION")

    def test_manifest_drift_requires_explicit_update_mode(self) -> None:
        with self._git_repo_with_current_lock() as root:
            manifest = root / "docs" / "specs" / "prompt-document-lock" / "LOCK.json"
            manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(PromptLockError, "LOCK.json changed"):
                validate_lock(root, base_ref="HEAD")

    def test_new_surface_requires_explicit_lock_renewal(self) -> None:
        with self._git_repo_with_current_lock() as root:
            manifest = root / "docs" / "specs" / "prompt-document-lock" / "LOCK.json"
            lock = json.loads(manifest.read_text(encoding="utf-8"))
            lock["surfaces"] = [
                surface
                for surface in lock["surfaces"]
                if surface["path"] != "templates/agents/sol-executor.toml"
            ]
            manifest.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
            (root / "templates" / "agents" / "sol-executor.toml").unlink()
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "test: establish previous lock"], cwd=root, check=True)

            current_manifest = ROOT / "docs" / "specs" / "prompt-document-lock" / "LOCK.json"
            shutil.copyfile(current_manifest, manifest)
            shutil.copyfile(
                ROOT / "templates" / "agents" / "sol-executor.toml",
                root / "templates" / "agents" / "sol-executor.toml",
            )

            with self.assertRaisesRegex(PromptLockError, "LOCK.json changed"):
                validate_lock(root, base_ref="HEAD")
            report = validate_lock(root, base_ref="HEAD", allow_lock_update=True)
            added = next(
                item for item in report["surfaces"] if item["id"] == "sol-executor-agent"
            )
            self.assertTrue(added["added"])

    def test_mirrored_policy_drift_is_rejected(self) -> None:
        with self._git_repo_with_current_lock() as root:
            policy = root / "plugin" / "plugins" / "pilotfish-codex" / "skills" / "pilotfish-orchestration" / "references" / "orchestration-policy.md"
            policy.write_text(policy.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(PromptLockError, "mirror"):
                validate_lock(root, base_ref="HEAD")
