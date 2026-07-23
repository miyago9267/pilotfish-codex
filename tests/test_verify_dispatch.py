from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))
import stage_smoke_home  # noqa: E402
import verify_dispatch  # noqa: E402
from stage_smoke_home import StageError, materialize  # noqa: E402
from verify_dispatch import RoleBinding, build_codex_command, hash_inputs, inspect_dispatch, receipt_payload, validate_home_pair, validate_receipt, validate_stage_layout  # noqa: E402

PARENT = "parent-runtime-id"
CHILD = "child-runtime-id"
CALL = "call-1"
WAIT_CALL = "wait-1"


def parent_events(arguments: dict | None = None, version: str = "v2") -> list[dict]:
    arguments = arguments or {"message": "ready", "agent_type": "scout", "task_name": "model_probe_scout", "fork_turns": "none"}
    return [
        {"type": "session_meta", "payload": {"id": PARENT}},
        {"type": "turn_context", "payload": {"model": "gpt-5.6-terra", "effort": "low", "multi_agent_version": version}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "namespace": "any-upstream-value", "call_id": CALL, "arguments": json.dumps(arguments)}},
        {"type": "event_msg", "payload": {"type": "sub_agent_activity", "kind": "started", "event_id": CALL, "agent_thread_id": CHILD}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "wait_agent", "call_id": WAIT_CALL, "arguments": json.dumps({"timeout_ms": 30000})}},
    ]


def child_events(model: str = "gpt-5.6-luna", effort: str = "low") -> list[dict]:
    return [{"type": "session_meta", "payload": {"id": CHILD, "parent_thread_id": PARENT}}, {"type": "turn_context", "payload": {"model": model, "effort": effort}}]


def make_home(path: Path) -> None:
    path.mkdir()
    shutil.copy2(ROOT / "templates" / "config.snippet.toml", path / "config.toml")
    shutil.copytree(ROOT / "templates" / "agents", path / "agents")
    shutil.copy2(ROOT / "templates" / "agents-md.orchestration.md", path / "AGENTS.md")


REAL_PUBLISH_NO_REPLACE = stage_smoke_home.publish_no_replace


def publish_no_replace_fixture(
    temporary: Path,
    destination: Path,
    active: Path,
    source_snapshots,
    projection_snapshot,
) -> None:
    """Exercise publication checks without requiring Darwin in unit tests."""
    stage_smoke_home._revalidate_sources(source_snapshots)
    stage_smoke_home._revalidate_projection(projection_snapshot)
    active_required = stage_smoke_home._required_input_projection(active)
    staged_required = stage_smoke_home._required_input_projection(temporary)
    if active_required != staged_required:
        raise StageError("required inputs changed before publication")
    stage_smoke_home._revalidate_sources(source_snapshots)
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    else:
        raise StageError("staged destination appeared during publication")
    os.rename(temporary, destination)


class NativeEvidenceTests(unittest.TestCase):
    def test_live_command_allows_the_verified_clean_non_git_cwd(self) -> None:
        command = build_codex_command(
            codex_bin="codex",
            cwd=Path("/tmp/clean-smoke"),
            parent_model="gpt-5.6-terra",
        )

        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--strict-config", command)
        self.assertEqual(command[command.index("-C") + 1], "/tmp/clean-smoke")
        self.assertIn("wait_agent exactly once", command[-1])
        self.assertIn("a second spawn", command[-1])

    binding = RoleBinding("gpt-5.6-luna", "low")

    def test_namespace_independent_typed_evidence_is_native_ok(self) -> None:
        verdict = inspect_dispatch(parent_events(), child_events(), expected_role=self.binding)
        self.assertEqual((verdict.status, verdict.reason_code, verdict.child_created), ("NATIVE_OK", "native_verified", "yes"))
        self.assertEqual(len(verdict.parent_ref or ""), 16)
        self.assertNotEqual(verdict.parent_ref, PARENT)

    def test_service_tier_wins_over_missing_correlation(self) -> None:
        args = {"message": "ready", "agent_type": "scout", "task_name": "model_probe_scout", "fork_turns": "none", "service_tier": "fast"}
        events = parent_events(args)
        events[-2]["payload"]["event_id"] = "other"
        verdict = inspect_dispatch(events, [], expected_role=self.binding)
        self.assertEqual((verdict.status, verdict.reason_code, verdict.phase), ("FAILED", "service_tier_override_forbidden", "dispatch"))

    def test_untyped_and_policy_failures_are_fail_closed(self) -> None:
        untyped = parent_events(); untyped.append({"type": "response_item", "payload": {"type": "function_call", "name": "spawn_untyped"}})
        self.assertEqual(inspect_dispatch(untyped, [], expected_role=self.binding).reason_code, "untyped_fallback_detected")
        bad = parent_events({"message": "", "agent_type": "scout", "task_name": "model_probe_scout", "fork_turns": "none"})
        self.assertEqual(inspect_dispatch(bad, [], expected_role=self.binding).reason_code, "policy_violation")

    def test_second_typed_spawn_is_a_policy_violation(self) -> None:
        events = parent_events()
        events.insert(3, dict(events[2], payload=dict(events[2]["payload"])))
        verdict = inspect_dispatch(events, [], expected_role=self.binding)
        self.assertEqual((verdict.status, verdict.reason_code), ("FAILED", "policy_violation"))

    def test_wait_agent_evidence_is_exactly_once_and_after_spawn(self) -> None:
        missing = parent_events()
        missing.pop()
        duplicate = parent_events()
        duplicate.append(dict(duplicate[-1], payload=dict(duplicate[-1]["payload"])))
        wrong_order = parent_events()
        wrong_order.insert(2, wrong_order.pop())

        self.assertEqual(
            inspect_dispatch(missing, child_events(), expected_role=self.binding).reason_code,
            "policy_violation",
        )
        self.assertEqual(
            inspect_dispatch(duplicate, child_events(), expected_role=self.binding).reason_code,
            "policy_violation",
        )
        self.assertEqual(
            inspect_dispatch(wrong_order, child_events(), expected_role=self.binding).reason_code,
            "policy_violation",
        )

    def test_evidence_absence_and_binding_mismatches_have_precise_reasons(self) -> None:
        self.assertEqual(inspect_dispatch(parent_events()[:2], [], expected_role=self.binding).reason_code, "native_spawn_evidence_missing")
        self.assertEqual(inspect_dispatch(parent_events(), [], expected_role=self.binding).reason_code, "child_evidence_missing")
        self.assertEqual(inspect_dispatch(parent_events(), child_events(model="wrong"), expected_role=self.binding).reason_code, "child_model_mismatch")
        self.assertEqual(inspect_dispatch(parent_events(), child_events(effort="medium"), expected_role=self.binding).reason_code, "child_effort_mismatch")
        self.assertEqual(inspect_dispatch(parent_events(version="v1"), child_events(), expected_role=self.binding).reason_code, "native_v2_selection_mismatch")


class NativeHomeAndReceiptTests(unittest.TestCase):
    def test_home_pair_rejects_alias_and_nesting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); active = root / "active"; staged = root / "staged"
            make_home(active); make_home(staged)
            self.assertEqual(validate_home_pair(active, staged), (active.resolve(), staged.resolve()))
            with self.assertRaises(Exception):
                validate_home_pair(active, active)
            with self.assertRaises(Exception):
                validate_home_pair(active, active / "nested")

    def test_layout_allowlist_and_external_resource_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"; make_home(home)
            self.assertIsNone(validate_stage_layout(home))
            (home / "untrusted.txt").write_text("x")
            self.assertEqual(validate_stage_layout(home), "stage_layout_untrusted")
            (home / "untrusted.txt").unlink()
            (home / "config.toml").write_text('[mcp_servers.x]\ncommand = "/bin/evil"\n')
            self.assertEqual(validate_stage_layout(home), "external_input_unowned")

    def test_active_config_projection_rejects_any_role_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            make_home(active)
            with (active / "config.toml").open("a", encoding="utf-8") as config:
                config.write('\n[agents.rogue]\ndescription = "unapproved"\n')

            self.assertEqual(
                validate_stage_layout(active, active_home=True),
                "role_layer_unapproved",
            )
            with self.assertRaisesRegex(StageError, "required native V2"):
                materialize(active, root / "staged")
            self.assertFalse((root / "staged").exists())

    def test_preflight_projects_unknown_active_metadata_but_rejects_staged_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); active = root / "active"; staged = root / "staged"
            make_home(active); make_home(staged)
            metadata_name = ".codex-global-state.json"
            (active / metadata_name).write_text("runtime-state")
            smoke_cwd = root / "smoke"; smoke_cwd.mkdir()
            args = Namespace(
                active_codex_home=active,
                codex_home=staged,
                repository_root=ROOT,
                codex_cwd=smoke_cwd,
                role="scout",
                parent_model="gpt-5.6-sol",
            )

            self.assertIsInstance(verify_dispatch._preflight(args), tuple)
            (staged / metadata_name).write_text("runtime-state")
            original_hash_inputs = verify_dispatch.hash_inputs

            def reject_untrusted_staged_hash(home: Path):
                if home.resolve() == staged.resolve():
                    raise AssertionError("untrusted staged metadata was hashed")
                return original_hash_inputs(home)

            with patch(
                "verify_dispatch.hash_inputs",
                side_effect=reject_untrusted_staged_hash,
            ):
                result = verify_dispatch._preflight(args)

            self.assertIsInstance(result, verify_dispatch.Verdict)
            self.assertEqual(result.reason_code, "stage_layout_untrusted")

    def test_receipt_keys_hashes_and_matrix_are_strict(self) -> None:
        verdict = inspect_dispatch(parent_events(), child_events(), expected_role=RoleBinding("gpt-5.6-luna", "low"))
        hashes = {"config": "a" * 64, "role_manifest": "b" * 64, "policy": "c" * 64}
        payload = receipt_payload(verdict, codex_version="0.145.0", active=hashes, target=hashes)
        validate_receipt(payload)
        self.assertTrue(set(payload) <= verify_dispatch.RECEIPT_KEYS)
        payload["raw_id"] = PARENT
        with self.assertRaises(Exception):
            validate_receipt(payload)

    def test_receipt_rejects_impossible_execution_and_native_success_cells(self) -> None:
        hashes = {"config": "a" * 64, "role_manifest": "b" * 64, "policy": "c" * 64}
        with self.assertRaises(Exception):
            receipt_payload(verify_dispatch._verdict("FAILED", "codex_exec_failed", phase="execution-pre-child", child_created="yes"), codex_version="0.145.0", active=hashes, target=hashes)
        success = receipt_payload(inspect_dispatch(parent_events(), child_events(), expected_role=RoleBinding("gpt-5.6-luna", "low")), codex_version="0.145.0", active=hashes, target=hashes)
        success["target_policy_sha256"] = "d" * 64
        with self.assertRaises(Exception):
            validate_receipt(success)

    def test_receipts_require_all_hashes_and_redacted_preflight_shape(self) -> None:
        hashes = {"config": "a" * 64, "role_manifest": "b" * 64, "policy": "c" * 64}
        verdict = verify_dispatch._verdict("SKIPPED", "native_schema_introspection_unavailable", phase="preflight", child_created="no")
        payload = receipt_payload(verdict, codex_version="unknown", active=hashes, target=hashes)
        validate_receipt(payload)
        del payload["target_policy_sha256"]
        with self.assertRaises(Exception):
            validate_receipt(payload)

    def test_missing_hashed_input_is_not_an_empty_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"; home.mkdir()
            with self.assertRaises(Exception):
                hash_inputs(home)

    def test_missing_one_required_role_is_hash_input_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"; make_home(home)
            (home / "agents" / "scout.toml").unlink()
            with self.assertRaises(Exception):
                hash_inputs(home)

    def test_hash_inputs_rejects_required_input_symlinks_without_reading_target(self) -> None:
        relative_inputs = (
            Path("config.toml"),
            Path("AGENTS.md"),
            Path("agents/scout.toml"),
        )
        for relative in relative_inputs:
            with (
                self.subTest(input=relative.as_posix()),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                home = root / "home"
                make_home(home)
                outside = root / "outside"
                outside.write_bytes(b"must-not-read")
                source = home / relative
                source.unlink()
                source.symlink_to(outside)
                original_open = os.open

                def reject_outside_open(path, flags, mode=0o777, *, dir_fd=None):
                    if Path(path) == outside:
                        raise AssertionError("external symlink target was read")
                    if dir_fd is None:
                        return original_open(path, flags, mode)
                    return original_open(path, flags, mode, dir_fd=dir_fd)

                with patch(
                    "verify_dispatch.os.open",
                    side_effect=reject_outside_open,
                ):
                    with self.assertRaises(verify_dispatch.ReceiptError):
                        hash_inputs(home)

    def test_hash_inputs_rejects_required_input_mutation_between_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            make_home(home)
            config = home / "config.toml"
            original = verify_dispatch._role_manifest

            def mutate_before_manifest(manifest_home: Path):
                config.write_bytes(config.read_bytes() + b"\n")
                return original(manifest_home)

            with patch(
                "verify_dispatch._role_manifest",
                side_effect=mutate_before_manifest,
            ):
                with self.assertRaisesRegex(
                    verify_dispatch.ReceiptError,
                    "mutated",
                ):
                    hash_inputs(home)

    def test_retired_cli_options_fail_before_any_home_or_receipt(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            result = verify_dispatch.main(["--mode", "native"])
        self.assertEqual(result, 1)
        self.assertIn("cli_input_invalid", stderr.getvalue())


class StageSmokeHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.publisher_patch = patch(
            "stage_smoke_home.publish_no_replace",
            new=publish_no_replace_fixture,
        )
        self.publisher_patch.start()
        self.addCleanup(self.publisher_patch.stop)

    def test_production_publisher_fails_closed_off_darwin(self) -> None:
        with (
            patch.object(stage_smoke_home.sys, "platform", "linux"),
            self.assertRaisesRegex(
                StageError,
                "atomic no-replace publication is unavailable",
            ),
        ):
            REAL_PUBLISH_NO_REPLACE(
                Path("/unused/temporary"),
                Path("/unused/destination"),
                Path("/unused/active"),
                (),
                (),
            )

    def test_active_root_runtime_metadata_is_projected_out_without_inspection(self) -> None:
        metadata_names = (
            ".DS_Store",
            ".app-server-state-reconciled-v1",
            ".codex-global-state.json",
            ".codex-global-state.json.bak",
            "..codex-global-state.json.tmp-writer-1",
            ".future-runtime-metadata",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); active = root / "active"; staged = root / "staged"
            make_home(active)
            active_real = active.resolve()
            sentinels = {
                name: f"must-not-stage:{index}:{name}".encode()
                for index, name in enumerate(metadata_names)
            }
            for name, content in sentinels.items():
                (active / name).write_bytes(content)
            ignored_directory = active / ".future-runtime-directory"
            ignored_directory.mkdir()
            nested_sentinel = b"must-not-stage:nested-runtime-metadata"
            (ignored_directory / "private-state").write_bytes(nested_sentinel)
            outside = root / "outside-runtime-state"
            outside.write_bytes(b"must-not-stage:external-runtime-metadata")
            ignored_symlink = active / ".future-runtime-symlink"
            ignored_symlink.symlink_to(outside)
            ignored_fifo = active / ".future-runtime-fifo"
            os.mkfifo(ignored_fifo)
            ignored_root_names = set(sentinels) | {
                ignored_directory.name,
                ignored_symlink.name,
                ignored_fifo.name,
            }

            original_lstat = Path.lstat
            original_path_open = Path.open
            original_open = os.open

            def reject_metadata_lstat(path: Path):
                if path.parent == active_real and path.name in ignored_root_names:
                    raise AssertionError(f"metadata was inspected: {path.name}")
                return original_lstat(path)

            def reject_metadata_open(path, flags, mode=0o777, *, dir_fd=None):
                candidate = Path(path)
                if candidate.parent == active_real and candidate.name in ignored_root_names:
                    raise AssertionError(f"metadata bytes were read: {candidate.name}")
                if dir_fd is None:
                    return original_open(path, flags, mode)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            def reject_metadata_path_open(path: Path, *args, **kwargs):
                if path.parent == active_real and path.name in ignored_root_names:
                    raise AssertionError(f"metadata bytes were read: {path.name}")
                return original_path_open(path, *args, **kwargs)

            with (
                patch.object(Path, "lstat", new=reject_metadata_lstat),
                patch.object(Path, "open", new=reject_metadata_path_open),
                patch("stage_smoke_home.os.open", side_effect=reject_metadata_open),
            ):
                self.assertIsNone(validate_stage_layout(active, active_home=True))
                active_hashes = hash_inputs(active)
                materialize(active, staged)

            self.assertEqual(active_hashes, hash_inputs(staged))
            self.assertEqual(
                {path.name for path in staged.iterdir()},
                {"config.toml", "agents", "AGENTS.md"},
            )
            staged_bytes = b"".join(
                path.read_bytes()
                for path in staged.rglob("*")
                if path.is_file()
            )
            for content in sentinels.values():
                self.assertNotIn(content, staged_bytes)
            self.assertNotIn(nested_sentinel, staged_bytes)
            self.assertNotIn(outside.read_bytes(), staged_bytes)

    def test_unknown_root_metadata_is_rejected_from_the_staged_home(self) -> None:
        metadata_names = (
            ".DS_Store",
            ".app-server-state-reconciled-v1",
            ".codex-global-state.json",
            ".codex-global-state.json.bak",
            "..codex-global-state.json.tmp-writer-1",
            ".future-runtime-metadata",
        )
        for name in metadata_names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                staged = Path(directory) / "staged"
                make_home(staged)
                (staged / name).write_bytes(b"unapproved")

                self.assertEqual(
                    validate_stage_layout(staged),
                    "stage_layout_untrusted",
                )

    def test_known_runtime_metadata_is_ignored_without_inspection(self) -> None:
        runtime_files = {
            "history.jsonl",
            "models_cache.json",
            "version.json",
            "state_5.sqlite",
            "state_5.sqlite-wal",
            "state_5.sqlite-shm",
        }
        runtime_directories = {
            "log",
            "sessions",
            "shell_snapshots",
            "dispatch-receipts",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            staged = root / "staged"
            make_home(active)
            (active / "auth.json").write_text("credential")
            for name in runtime_files:
                (active / name).write_bytes(f"ignored:{name}".encode())
            for name in runtime_directories:
                runtime_directory = active / name
                runtime_directory.mkdir()
                (runtime_directory / "sentinel").write_bytes(
                    f"ignored:{name}".encode()
                )
            outside = root / "outside-runtime"
            outside.write_bytes(b"ignored:tmp")
            (active / "tmp").symlink_to(outside)
            ignored_names = runtime_files | runtime_directories | {"tmp"}
            active_real = active.resolve()
            original_lstat = Path.lstat

            def reject_runtime_lstat(path: Path):
                if path.parent == active_real and path.name in ignored_names:
                    raise AssertionError(f"runtime metadata was inspected: {path.name}")
                return original_lstat(path)

            with patch.object(Path, "lstat", new=reject_runtime_lstat):
                self.assertIsNone(validate_stage_layout(active, active_home=True))
                materialize(active, staged)

            self.assertEqual(
                {path.name for path in staged.iterdir()},
                {"config.toml", "agents", "AGENTS.md", "auth.json"},
            )
            self.assertTrue(ignored_names.isdisjoint(path.name for path in staged.iterdir()))
            self.assertEqual(hash_inputs(active), hash_inputs(staged))

    def test_staging_projects_only_required_native_v2_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            staged = root / "staged"
            make_home(active)
            with (active / "config.toml").open("a", encoding="utf-8") as config:
                config.write(
                    '\n[mcp_servers.external]\ncommand = "/bin/ignored"\n'
                    '\n[projects."/outside"]\ntrust_level = "trusted"\n'
                )

            self.assertIsNone(validate_stage_layout(active, active_home=True))
            materialize(active, staged)

            self.assertEqual(
                (staged / "config.toml").read_bytes(),
                stage_smoke_home.SMOKE_CONFIG,
            )
            self.assertNotIn(b"/bin/ignored", (staged / "config.toml").read_bytes())
            self.assertEqual(hash_inputs(active), hash_inputs(staged))
            self.assertIsNone(validate_stage_layout(staged))

    def test_required_projected_inputs_reject_symlinks_and_special_files(self) -> None:
        relative_inputs = (
            Path("config.toml"),
            Path("AGENTS.md"),
            Path("agents/scout.toml"),
            Path("auth.json"),
        )
        replacements = (
            (
                "external symlink",
                lambda path, root: path.symlink_to(root / "outside"),
            ),
            ("fifo", lambda path, _root: os.mkfifo(path)),
        )
        for relative in relative_inputs:
            for label, replace in replacements:
                with (
                    self.subTest(input=relative.as_posix(), hazard=label),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    active = root / "active"
                    make_home(active)
                    outside = root / "outside"
                    outside.write_bytes(b"external")
                    source = active / relative
                    source.unlink(missing_ok=True)
                    replace(source, root)

                    self.assertEqual(
                        validate_stage_layout(active, active_home=True),
                        "stage_layout_untrusted",
                    )
                    with self.assertRaises(StageError):
                        materialize(active, root / "staged")

    def test_required_projected_inputs_reject_unreadable_files(self) -> None:
        relative_inputs = (
            Path("config.toml"),
            Path("AGENTS.md"),
            Path("agents/scout.toml"),
            Path("auth.json"),
        )
        for relative in relative_inputs:
            with (
                self.subTest(input=relative.as_posix()),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                active = root / "active"
                make_home(active)
                source = active / relative
                if not source.exists():
                    source.write_bytes(b"runtime")
                source.chmod(0)
                try:
                    self.assertEqual(
                        validate_stage_layout(active, active_home=True),
                        "stage_layout_untrusted",
                    )
                    with self.assertRaises(StageError):
                        materialize(active, root / "staged")
                finally:
                    source.chmod(0o600)

    def test_required_projected_inputs_reject_copy_time_mutation(self) -> None:
        relative_inputs = (
            Path("config.toml"),
            Path("AGENTS.md"),
            Path("agents/scout.toml"),
            Path("auth.json"),
        )
        for relative in relative_inputs:
            with (
                self.subTest(input=relative.as_posix()),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                active = root / "active"
                make_home(active)
                source_to_mutate = active / relative
                if not source_to_mutate.exists():
                    source_to_mutate.write_bytes(b"runtime")
                source_to_mutate = source_to_mutate.resolve()
                original = stage_smoke_home._regular_source
                mutated = False

                def mutate_after_stat(source: Path, confined_home: Path):
                    nonlocal mutated
                    before = original(source, confined_home)
                    if source == source_to_mutate and not mutated:
                        source.write_bytes(source.read_bytes() + b"\n")
                        mutated = True
                    return before

                with patch(
                    "stage_smoke_home._regular_source",
                    side_effect=mutate_after_stat,
                ):
                    with self.assertRaisesRegex(
                        StageError,
                        "replaced while staging",
                    ):
                        materialize(active, root / "staged")

                self.assertTrue(mutated)
                self.assertFalse((root / "staged").exists())
                self.assertEqual(
                    list(root.glob(".staged.pilotfish-stage-*")),
                    [],
                )

    def test_required_source_mutation_before_publication_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            make_home(active)
            source = active / "config.toml"
            original = stage_smoke_home._revalidate_sources

            def mutate_before_revalidation(snapshots):
                source.write_bytes(source.read_bytes() + b"\n")
                original(snapshots)

            with patch(
                "stage_smoke_home._revalidate_sources",
                side_effect=mutate_before_revalidation,
            ):
                with self.assertRaisesRegex(
                    StageError,
                    "changed before staging publication",
                ):
                    materialize(active, root / "staged")

            self.assertFalse((root / "staged").exists())
            self.assertEqual(list(root.glob(".staged.pilotfish-stage-*")), [])

    def test_required_role_mutation_at_publication_seam_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            make_home(active)
            role = active / "agents" / "scout.toml"
            original = stage_smoke_home._revalidate_projection
            mutated = False

            def mutate_during_projection(snapshot):
                nonlocal mutated
                original(snapshot)
                if not mutated:
                    role.write_bytes(role.read_bytes() + b"\n# late mutation\n")
                    mutated = True

            with patch(
                "stage_smoke_home._revalidate_projection",
                side_effect=mutate_during_projection,
            ):
                with self.assertRaisesRegex(
                    StageError,
                    "required inputs changed before publication",
                ):
                    materialize(active, root / "staged")

            self.assertTrue(mutated)
            self.assertFalse((root / "staged").exists())
            self.assertEqual(list(root.glob(".staged.pilotfish-stage-*")), [])

    def test_required_input_appearance_before_publication_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            make_home(active)
            original = stage_smoke_home._revalidate_sources

            def add_second_policy_after_copy(snapshots):
                original(snapshots)
                (active / "AGENTS.override.md").write_text("late policy")

            with patch(
                "stage_smoke_home._revalidate_sources",
                side_effect=add_second_policy_after_copy,
            ):
                with self.assertRaisesRegex(
                    StageError,
                    "active projection changed before publication",
                ):
                    materialize(active, root / "staged")

            self.assertFalse((root / "staged").exists())
            self.assertEqual(list(root.glob(".staged.pilotfish-stage-*")), [])

    def test_staging_copies_only_allowlisted_inputs_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); active = root / "active"; staged = root / "staged"
            make_home(active); (active / "auth.json").write_text("credential")
            stamp = "20260716-001307"
            (active / f"config.toml.pilotfish-codex-{stamp}").write_text("previous")
            (active / "agents" / f"scout.toml.pilotfish-codex-{stamp}").write_text("previous")
            result = materialize(active, staged)
            self.assertEqual(result, staged.resolve())
            self.assertTrue((staged / "auth.json").exists())
            self.assertEqual({p.name for p in staged.iterdir()}, {"config.toml", "agents", "AGENTS.md", "auth.json"})
            self.assertEqual({path.name for path in (staged / "agents").iterdir()}, {f"{role}.toml" for role in verify_dispatch.ROLES})
            self.assertIsNone(validate_stage_layout(staged))

    def test_staging_rejects_existing_and_nested_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); active = root / "active"; make_home(active)
            existing = root / "existing"; existing.mkdir()
            with self.assertRaises(StageError): materialize(active, existing)
            with self.assertRaises(StageError): materialize(active, active / "nested")

    def test_unhashed_agent_entry_is_rejected_by_stager_and_layout_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); active = root / "active"; make_home(active)
            (active / "agents" / "unhashed-policy.txt").write_text("unapproved")
            staged = root / "staged"

            with self.assertRaisesRegex(StageError, "unapproved"):
                materialize(active, staged)

            self.assertFalse(staged.exists())
            self.assertEqual(validate_stage_layout(active), "stage_layout_untrusted")

    def test_staging_cleanup_retry_removes_sensitive_temporary_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); active = root / "active"; make_home(active)
            (active / "auth.json").write_text("credential")
            with (
                patch(
                    "stage_smoke_home.publish_no_replace",
                    side_effect=StageError("publication blocked"),
                ),
                patch(
                    "stage_smoke_home.shutil.rmtree",
                    side_effect=OSError("blocked"),
                ),
            ):
                with self.assertRaisesRegex(StageError, "publication blocked"):
                    materialize(active, root / "staged")
            self.assertEqual(list(root.glob(".staged.pilotfish-stage-*")), [])


if __name__ == "__main__":
    unittest.main()
