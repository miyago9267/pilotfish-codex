"""Focused co-owned hook staging tests using temporary Codex homes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))
import install as installer  # noqa: E402
import stage_smoke_home  # noqa: E402
from stage_smoke_home import StageError  # noqa: E402


def _foreign_group(command: str) -> dict[str, object]:
    return {"matcher": "foreign", "hooks": [{"type": "command", "command": command}]}


def _portable_publish(
    temporary: Path,
    destination: Path,
    active: Path,
    source_snapshots,
    projection_snapshot,
) -> None:
    stage_smoke_home._revalidate_sources(source_snapshots)
    stage_smoke_home._revalidate_projection(projection_snapshot)
    if stage_smoke_home._required_input_projection(active) != (
        stage_smoke_home._required_input_projection(temporary)
    ):
        raise StageError("required inputs changed before publication")
    staged_hooks = (temporary / "hooks.json").read_bytes()
    source_hooks = stage_smoke_home.SOURCE_HOOK_REGISTRATION.read_bytes()
    if staged_hooks != source_hooks:
        raise StageError("clean staged hooks.json changed before publication")
    stage_smoke_home._revalidate_sources(source_snapshots)
    if destination.exists():
        raise StageError("staged destination appeared during publication")
    os.rename(temporary, destination)


class CoOwnedHookStagingTests(unittest.TestCase):
    def _installed_home(self, root: Path) -> Path:
        home = root / "active"
        installer.install(
            source_root=ROOT,
            codex_home=home,
            dry_run=False,
            check_codex=False,
        )
        return home

    def test_staging_excludes_foreign_hook_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            hooks = active / "hooks.json"
            document = json.loads(hooks.read_text())
            document["hooks"]["Stop"].insert(0, _foreign_group("/bin/foreign-stage"))
            hooks.write_text(json.dumps(document, indent=2) + "\n")
            staged = root / "staged"

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=_portable_publish,
            ):
                stage_smoke_home.materialize(active, staged)

            self.assertEqual(
                (staged / "hooks.json").read_bytes(),
                (ROOT / "templates" / "hooks.json").read_bytes(),
            )
            self.assertNotIn(b"foreign-stage", (staged / "hooks.json").read_bytes())

    def test_active_hook_script_rollback_backup_is_omitted_from_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            backup = active / "hooks" / (
                "pilotfish_autoroute_gate.py."
                "pilotfish-codex-20260804-172335-358116"
            )
            backup.write_bytes(b"previous hook script\n")
            staged = root / "staged"

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=_portable_publish,
            ):
                stage_smoke_home.materialize(active, staged)

            self.assertTrue((staged / stage_smoke_home.HOOK_SCRIPT).is_file())
            self.assertFalse((staged / "hooks" / backup.name).exists())

    def test_legacy_role_rollback_backup_date_shape_is_omitted_from_stage(self) -> None:
        self.assertTrue(
            stage_smoke_home._rollback_backup(
                Path("agents/plan-verifier.toml.pilotfish-codex-20260807")
            )
        )

    def test_reconciled_v4_state_is_accepted_for_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            policy = active / "AGENTS.md"
            policy.write_bytes(policy.read_bytes() + b"\n# current rule\n")
            installer.install(
                source_root=ROOT,
                codex_home=active,
                dry_run=False,
                check_codex=False,
                reconcile_current=True,
            )
            staged = root / "staged"

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=_portable_publish,
            ):
                stage_smoke_home.materialize(active, staged)

            self.assertIn(b"# current rule", (staged / "AGENTS.md").read_bytes())

    def test_other_hook_backup_shapes_remain_rejected(self) -> None:
        names = (
            "other.py.pilotfish-codex-20260804-172335-358116",
            "pilotfish_autoroute_gate.py.pilotfish-codex-20260804",
            (
                "pilotfish_autoroute_gate.py."
                "pilotfish-codex-20260804-172335-358116."
                "pilotfish-v1.2-pristine"
            ),
        )
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                active = self._installed_home(root)
                (active / "hooks" / name).write_bytes(b"unapproved backup\n")

                with self.assertRaisesRegex(StageError, "unapproved entry: hooks/"):
                    stage_smoke_home.materialize(active, root / "staged")
                self.assertFalse((root / "staged").exists())

    def test_hook_script_rollback_backup_symlink_remains_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            target = root / "external-hook-backup.py"
            target.write_bytes(b"external hook backup\n")
            backup = active / "hooks" / (
                "pilotfish_autoroute_gate.py."
                "pilotfish-codex-20260804-172335-358116"
            )
            backup.symlink_to(target)

            with self.assertRaisesRegex(StageError, "unapproved entry: hooks/"):
                stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_state_proven_effective_policy_symlink_stages_as_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            policy = active / "AGENTS.md"
            target = root / "owned-policy.md"
            target.write_bytes(policy.read_bytes())
            policy.unlink()
            policy.symlink_to(target)
            staged = root / "staged"

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=_portable_publish,
            ):
                stage_smoke_home.materialize(active, staged)

            staged_policy = staged / "AGENTS.md"
            self.assertEqual(staged_policy.read_bytes(), target.read_bytes())
            self.assertFalse(staged_policy.is_symlink())
            self.assertFalse(any(path.is_symlink() for path in staged.rglob("*")))

    def test_effective_policy_symlink_target_mutation_before_publication_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            policy = active / "AGENTS.md"
            target = root / "owned-policy.md"
            target.write_bytes(policy.read_bytes())
            policy.unlink()
            policy.symlink_to(target)

            def mutate_then_publish(*args):
                target.write_bytes(target.read_bytes() + b"late mutation\n")
                return _portable_publish(*args)

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=mutate_then_publish,
            ):
                with self.assertRaisesRegex(
                    StageError,
                    "source changed before staging publication",
                ):
                    stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_effective_policy_symlink_swap_before_publication_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            policy = active / "AGENTS.md"
            target = root / "owned-policy.md"
            replacement = root / "replacement-policy.md"
            target.write_bytes(policy.read_bytes())
            replacement.write_bytes(target.read_bytes())
            policy.unlink()
            policy.symlink_to(target)

            def swap_then_publish(*args):
                policy.unlink()
                policy.symlink_to(replacement)
                return _portable_publish(*args)

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=swap_then_publish,
            ):
                with self.assertRaisesRegex(
                    StageError,
                    "source changed before staging publication",
                ):
                    stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_foreign_effective_policy_symlink_rejects_without_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            policy = active / "AGENTS.md"
            target = root / "foreign-policy.md"
            target.write_bytes(b"foreign policy\n")
            policy.unlink()
            policy.symlink_to(target)

            with self.assertRaisesRegex(
                StageError,
                "effective policy does not match committed provenance",
            ):
                stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_effective_policy_symlink_without_committed_state_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            policy = active / "AGENTS.md"
            target = root / "unproven-policy.md"
            target.write_bytes(policy.read_bytes())
            policy.unlink()
            policy.symlink_to(target)
            active.with_name(
                f"{active.name}.pilotfish-install-state.json"
            ).unlink()

            with self.assertRaisesRegex(
                StageError,
                "effective policy symlink requires committed provenance",
            ):
                stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_non_policy_symlink_rejects_without_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            credential = root / "foreign-auth.json"
            credential.write_bytes(b"{}\n")
            (active / "auth.json").symlink_to(credential)

            with self.assertRaisesRegex(StageError, "unapproved entry: auth.json"):
                stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_active_hook_mutation_before_publication_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)
            hooks = active / "hooks.json"

            def mutate_then_publish(*args):
                document = json.loads(hooks.read_text())
                document["hooks"]["Stop"].insert(0, _foreign_group("/bin/race"))
                hooks.write_text(json.dumps(document, indent=2) + "\n")
                return _portable_publish(*args)

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=mutate_then_publish,
            ):
                with self.assertRaisesRegex(StageError, "active projection changed"):
                    stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_staged_hook_foreign_injection_before_publication_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = self._installed_home(root)

            def mutate_then_publish(temporary, *args):
                hooks = temporary / "hooks.json"
                document = json.loads(hooks.read_text())
                document["hooks"]["Stop"].insert(0, _foreign_group("/bin/staged-race"))
                hooks.write_text(json.dumps(document, indent=2) + "\n")
                return _portable_publish(temporary, *args)

            with mock.patch.object(
                stage_smoke_home,
                "publish_no_replace",
                side_effect=mutate_then_publish,
            ):
                with self.assertRaisesRegex(StageError, "clean staged hooks.json changed"):
                    stage_smoke_home.materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())


if __name__ == "__main__":
    unittest.main()
